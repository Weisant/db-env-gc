"""Docker Hub 镜像解析工具。

这个模块负责根据任务中的数据库类型和版本，
判断 Docker Hub 上是否存在可直接使用的官方镜像 tag。
如果不存在，主流程会退回到 `Dockerfile` 自定义镜像分支。
"""

from __future__ import annotations

import json
import subprocess
from urllib import error, parse, request

from agent.models import ImageResolution, TaskInput


DOCKER_HUB_API_BASE = "https://hub.docker.com/v2"
REQUEST_TIMEOUT_SECONDS = 15

# 第一版只维护少量高频别名，避免把第三方或非官方仓库误当成默认结果。
REPOSITORY_ALIASES: dict[str, list[tuple[str, str]]] = {
    "postgres": [("library", "postgres")],
    "postgresql": [("library", "postgres")],
    "mysql": [("library", "mysql")],
    "redis": [("library", "redis")],
    "mongodb": [("library", "mongo")],
    "mongo": [("library", "mongo")],
    "mariadb": [("library", "mariadb")],
}


def resolve_image_source(task: TaskInput) -> ImageResolution:
    """解析应使用官方镜像还是 Dockerfile 自定义镜像。"""
    normalized_db_type = _normalize_db_type(task.db_type)
    requested_version = task.version.strip()
    checked_candidates: list[str] = []

    if not normalized_db_type or not requested_version:
        return ImageResolution(
            db_type=task.db_type,
            requested_version=requested_version,
            namespace="",
            repository="",
            matched_tag="",
            image_ref="",
            strategy="custom_dockerfile",
            availability="lookup_failed",
            checked_candidates=[],
            notes=["数据库类型或版本为空，无法安全判断官方镜像 tag，已回退到 Dockerfile。"],
        )

    try:
        for namespace, repository in _build_repository_candidates(normalized_db_type):
            checked_candidates.append(f"{namespace}/{repository}:{requested_version}")

            repo_exists = _repository_exists(namespace, repository)
            if not repo_exists:
                continue

            tag_exists = _tag_exists(namespace, repository, requested_version)
            related_tags = _list_related_tags(namespace, repository, requested_version)
            if tag_exists:
                image_ref = _build_image_ref(namespace, repository, requested_version)
                return ImageResolution(
                    db_type=task.db_type,
                    requested_version=requested_version,
                    namespace=namespace,
                    repository=repository,
                    matched_tag=requested_version,
                    image_ref=image_ref,
                    strategy="official_image",
                    availability="tag_found",
                    checked_candidates=checked_candidates,
                    notes=[f"Docker Hub 上存在官方镜像 tag：{namespace}/{repository}:{requested_version}"],
                )

            notes = [
                f"已确认官方仓库 {namespace}/{repository} 存在，但未找到精确 tag {requested_version}。"
            ]
            if related_tags:
                notes.append("相关 tag 参考：" + ", ".join(related_tags[:10]))
            return ImageResolution(
                db_type=task.db_type,
                requested_version=requested_version,
                namespace=namespace,
                repository=repository,
                matched_tag="",
                image_ref="",
                strategy="custom_dockerfile",
                availability="repo_found_tag_missing",
                checked_candidates=checked_candidates,
                notes=notes,
            )

        return ImageResolution(
            db_type=task.db_type,
            requested_version=requested_version,
            namespace="",
            repository="",
            matched_tag="",
            image_ref="",
            strategy="custom_dockerfile",
            availability="repo_missing",
            checked_candidates=checked_candidates,
            notes=["未找到可确认的 Docker Hub 官方仓库，已回退到 Dockerfile。"],
        )
    except RuntimeError as exc:
        return ImageResolution(
            db_type=task.db_type,
            requested_version=requested_version,
            namespace="",
            repository="",
            matched_tag="",
            image_ref="",
            strategy="custom_dockerfile",
            availability="lookup_failed",
            checked_candidates=checked_candidates,
            notes=[f"Docker Hub 查询失败，已保守回退到 Dockerfile：{exc}"],
        )


def _normalize_db_type(db_type: str) -> str:
    return db_type.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _build_repository_candidates(normalized_db_type: str) -> list[tuple[str, str]]:
    candidates = REPOSITORY_ALIASES.get(normalized_db_type)
    if candidates:
        return candidates
    return [("library", normalized_db_type)]


def _build_image_ref(namespace: str, repository: str, tag: str) -> str:
    repository_ref = repository if namespace == "library" else f"{namespace}/{repository}"
    return f"{repository_ref}:{tag}"


def _repository_exists(namespace: str, repository: str) -> bool:
    url = (
        f"{DOCKER_HUB_API_BASE}/namespaces/"
        f"{parse.quote(namespace)}/repositories/{parse.quote(repository)}"
    )
    status_code, _payload = _fetch_json(url, treat_404_as_none=True)
    return status_code == 200


def _tag_exists(namespace: str, repository: str, tag: str) -> bool:
    url = (
        f"{DOCKER_HUB_API_BASE}/namespaces/{parse.quote(namespace)}"
        f"/repositories/{parse.quote(repository)}/tags/{parse.quote(tag)}"
    )
    status_code, _payload = _fetch_json(url, treat_404_as_none=True)
    return status_code == 200


def _list_related_tags(namespace: str, repository: str, requested_version: str) -> list[str]:
    query = parse.urlencode(
        {
            "page_size": 10,
            "name": requested_version,
        }
    )
    url = (
        f"{DOCKER_HUB_API_BASE}/namespaces/{parse.quote(namespace)}"
        f"/repositories/{parse.quote(repository)}/tags?{query}"
    )
    status_code, payload = _fetch_json(url, treat_404_as_none=True)
    if status_code != 200 or not isinstance(payload, dict):
        return []

    results = payload.get("results")
    if not isinstance(results, list):
        return []

    related_tags: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            related_tags.append(name.strip())
    return related_tags


def _fetch_json(url: str, *, treat_404_as_none: bool = False) -> tuple[int, dict | None]:
    try:
        return _fetch_json_with_urllib(url, treat_404_as_none=treat_404_as_none)
    except RuntimeError as exc:
        return _fetch_json_with_curl(
            url,
            treat_404_as_none=treat_404_as_none,
            fallback_reason=str(exc),
        )


def _fetch_json_with_urllib(
    url: str,
    *,
    treat_404_as_none: bool = False,
) -> tuple[int, dict | None]:
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "db-env-gc/0.1",
            "Connection": "close",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
            payload = json.loads(body) if body else {}
            if isinstance(payload, dict):
                return response.status, payload
            return response.status, {"raw": payload}
    except error.HTTPError as exc:
        if treat_404_as_none and exc.code == 404:
            return 404, None
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def _fetch_json_with_curl(
    url: str,
    *,
    treat_404_as_none: bool = False,
    fallback_reason: str,
) -> tuple[int, dict | None]:
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--header",
        "Accept: application/json",
        "--header",
        "User-Agent: db-env-gc/0.1",
        "--write-out",
        "\n%{http_code}",
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
        raise RuntimeError(f"{fallback_reason}; curl fallback failed: {exc}") from exc

    output = completed.stdout
    if "\n" not in output:
        raise RuntimeError(
            f"{fallback_reason}; curl fallback returned malformed response: {completed.stderr.strip()}"
        )

    body, status_text = output.rsplit("\n", 1)
    try:
        status_code = int(status_text.strip())
    except ValueError as exc:
        raise RuntimeError(
            f"{fallback_reason}; curl fallback returned invalid status code: {status_text}"
        ) from exc

    if treat_404_as_none and status_code == 404:
        return 404, None
    if status_code >= 400:
        raise RuntimeError(
            f"{fallback_reason}; curl fallback HTTP {status_code}: {completed.stderr.strip() or body}"
        )

    payload = json.loads(body) if body else {}
    if isinstance(payload, dict):
        return status_code, payload
    return status_code, {"raw": payload}
