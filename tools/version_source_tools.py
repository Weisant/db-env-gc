"""数据库官方源码版本解析工具。

这个模块负责根据项目内置的官方源码源规则，
判断任务中请求的数据库版本是否真实存在。
"""

from __future__ import annotations

import subprocess
from urllib import error, parse, request

from agent.models import TaskInput, VersionResolution


REQUEST_TIMEOUT_SECONDS = 15

# 当前版本先覆盖项目里最常用的几类数据库。
# 后续要扩展时，只需要继续往这张表中补官方源码源规则。
SOURCE_CATALOG: dict[str, dict[str, object]] = {
    "redis": {
        "sources": [
            {
                "source_name": "Redis Official Downloads",
                "source_url": "https://download.redis.io/releases/",
                "strategy": "direct_archive",
                "archive_patterns": [
                    "redis-{version}.tar.gz",
                    "redis-{version}.tgz",
                ],
            },
            {
                "source_name": "Redis GitHub Source Tags",
                "source_url": "https://github.com/redis/redis",
                "strategy": "github_tag_archive",
                "archive_patterns": [
                    "https://github.com/redis/redis/archive/refs/tags/{version}.tar.gz",
                    "https://github.com/redis/redis/archive/refs/tags/{version}.zip",
                ],
            },
        ],
    },
    "postgres": {
        "sources": [
            {
                "source_name": "PostgreSQL Source Archive",
                "source_url": "https://ftp.postgresql.org/pub/source/",
                "strategy": "direct_archive",
                "archive_patterns": [
                    "v{version}/postgresql-{version}.tar.gz",
                    "v{version}/postgresql-{version}.tar.bz2",
                ],
            },
        ],
    },
    "postgresql": {
        "sources": [
            {
                "source_name": "PostgreSQL Source Archive",
                "source_url": "https://ftp.postgresql.org/pub/source/",
                "strategy": "direct_archive",
                "archive_patterns": [
                    "v{version}/postgresql-{version}.tar.gz",
                    "v{version}/postgresql-{version}.tar.bz2",
                ],
            },
        ],
    },
    "mysql": {
        "sources": [
            {
                "source_name": "MySQL GitHub Source Tags",
                "source_url": "https://github.com/mysql/mysql-server",
                "strategy": "github_tag_archive",
                "archive_patterns": [
                    "https://github.com/mysql/mysql-server/archive/refs/tags/mysql-{version}.tar.gz",
                ],
            },
        ],
    },
    "mongo": {
        "sources": [
            {
                "source_name": "MongoDB GitHub Source Tags",
                "source_url": "https://github.com/mongodb/mongo",
                "strategy": "github_tag_archive",
                "archive_patterns": [
                    "https://github.com/mongodb/mongo/archive/refs/tags/r{version}.tar.gz",
                    "https://github.com/mongodb/mongo/archive/refs/tags/v{version}.tar.gz",
                    "https://github.com/mongodb/mongo/archive/refs/tags/{version}.tar.gz",
                ],
            },
        ],
    },
    "mongodb": {
        "sources": [
            {
                "source_name": "MongoDB GitHub Source Tags",
                "source_url": "https://github.com/mongodb/mongo",
                "strategy": "github_tag_archive",
                "archive_patterns": [
                    "https://github.com/mongodb/mongo/archive/refs/tags/r{version}.tar.gz",
                    "https://github.com/mongodb/mongo/archive/refs/tags/v{version}.tar.gz",
                    "https://github.com/mongodb/mongo/archive/refs/tags/{version}.tar.gz",
                ],
            },
        ],
    },
}


def resolve_version_source(task: TaskInput) -> VersionResolution:
    """解析数据库版本是否存在于内置官方源码源中。"""
    normalized_db_type = _normalize_db_type(task.db_type)
    requested_version = task.version.strip()
    source_config = SOURCE_CATALOG.get(normalized_db_type)

    if not normalized_db_type or not requested_version:
        return VersionResolution(
            db_type=task.db_type,
            requested_version=requested_version,
            source_name="",
            source_url="",
            version_exists=False,
            matched_version="",
            matched_url="",
            lookup_strategy="none",
            availability="lookup_failed",
            checked_sources=[],
            checked_candidates=[],
            notes=["数据库类型或版本为空，无法确认该版本是否真实存在。"],
        )

    if source_config is None:
        return VersionResolution(
            db_type=task.db_type,
            requested_version=requested_version,
            source_name="",
            source_url="",
            version_exists=False,
            matched_version="",
            matched_url="",
            lookup_strategy="unconfigured_source",
            availability="source_not_configured",
            checked_sources=[],
            checked_candidates=[],
            notes=[f"当前未为数据库类型 {task.db_type} 配置官方源码源。"],
        )

    sources = source_config.get("sources")
    if not isinstance(sources, list) or not sources:
        return VersionResolution(
            db_type=task.db_type,
            requested_version=requested_version,
            source_name="",
            source_url="",
            version_exists=False,
            matched_version="",
            matched_url="",
            lookup_strategy="misconfigured_source",
            availability="lookup_failed",
            checked_sources=[],
            checked_candidates=[],
            notes=[f"数据库类型 {task.db_type} 的源码源配置为空或格式错误。"],
        )

    checked_sources: list[str] = []
    checked_candidates: list[str] = []
    failed_source_notes: list[str] = []

    for source in sources:
        if not isinstance(source, dict):
            continue

        source_name = str(source.get("source_name", "")).strip()
        source_url = str(source.get("source_url", "")).strip()
        lookup_strategy = str(source.get("strategy", "")).strip()
        archive_patterns = [str(item) for item in source.get("archive_patterns", [])]

        if not source_name or not source_url or not lookup_strategy or not archive_patterns:
            failed_source_notes.append(f"检测到无效源码源配置：{source!r}")
            continue

        checked_sources.append(source_url)
        current_candidates = _build_candidates(
            source_url=source_url,
            requested_version=requested_version,
            archive_patterns=archive_patterns,
        )
        checked_candidates.extend(current_candidates)

        try:
            for candidate_url in current_candidates:
                if _url_exists(candidate_url):
                    return VersionResolution(
                        db_type=task.db_type,
                        requested_version=requested_version,
                        source_name=source_name,
                        source_url=source_url,
                        version_exists=True,
                        matched_version=requested_version,
                        matched_url=candidate_url,
                        lookup_strategy=lookup_strategy,
                        availability="version_found",
                        checked_sources=checked_sources,
                        checked_candidates=checked_candidates,
                        notes=[f"已在官方源码源中确认版本存在：{candidate_url}"],
                    )
        except RuntimeError as exc:
            failed_source_notes.append(f"{source_name} 查询失败：{exc}")

    if failed_source_notes:
        return VersionResolution(
            db_type=task.db_type,
            requested_version=requested_version,
            source_name="",
            source_url="",
            version_exists=False,
            matched_version="",
            matched_url="",
            lookup_strategy="multiple_sources",
            availability="lookup_failed",
            checked_sources=checked_sources,
            checked_candidates=checked_candidates,
            notes=failed_source_notes,
        )

    return VersionResolution(
        db_type=task.db_type,
        requested_version=requested_version,
        source_name="",
        source_url="",
        version_exists=False,
        matched_version="",
        matched_url="",
        lookup_strategy="multiple_sources",
        availability="version_not_found",
        checked_sources=checked_sources,
        checked_candidates=checked_candidates,
        notes=[f"未在已配置的官方源码源中找到版本 {requested_version}。"],
    )


def _normalize_db_type(db_type: str) -> str:
    return db_type.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _build_candidates(
    *,
    source_url: str,
    requested_version: str,
    archive_patterns: list[str],
) -> list[str]:
    candidates: list[str] = []
    for pattern in archive_patterns:
        if pattern.startswith("http://") or pattern.startswith("https://"):
            candidates.append(pattern.format(version=requested_version))
            continue
        relative_path = pattern.format(version=requested_version)
        candidates.append(parse.urljoin(source_url, relative_path))
    return candidates


def _url_exists(url: str) -> bool:
    try:
        return _url_exists_with_urllib(url)
    except RuntimeError:
        return _url_exists_with_curl(url)


def _url_exists_with_urllib(url: str) -> bool:
    req = request.Request(
        url,
        headers={
            "User-Agent": "db-env-gc/0.1",
            "Connection": "close",
        },
        method="HEAD",
    )
    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 400
    except error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def _url_exists_with_curl(url: str) -> bool:
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--head",
        "--output",
        "/dev/null",
        "--write-out",
        "%{http_code}",
        "--user-agent",
        "db-env-gc/0.1",
        url,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"curl fallback failed: {exc}") from exc

    status_text = completed.stdout.strip()
    try:
        status_code = int(status_text)
    except ValueError as exc:
        raise RuntimeError(f"curl fallback returned invalid status code: {status_text}") from exc

    if status_code == 404:
        return False
    if status_code >= 400:
        raise RuntimeError(
            f"curl fallback HTTP {status_code}: {completed.stderr.strip() or 'request failed'}"
        )
    return 200 <= status_code < 400
