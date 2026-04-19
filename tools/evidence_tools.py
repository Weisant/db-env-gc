"""CVE 证据收集工具。

这一层只负责收集和整理外部证据，不直接给出最终复现结论。
"""

from __future__ import annotations

import json
import re
import subprocess
from html import unescape
from urllib import error, parse, request

from agent.models import EvidenceItem, TaskInput


REQUEST_TIMEOUT_SECONDS = 20
DATABASE_TYPE_ALIASES = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "redis": "redis",
    "mysql": "mysql",
    "mariadb": "mariadb",
    "mongodb": "mongo",
    "mongo": "mongo",
    "elasticsearch": "elasticsearch",
    "cassandra": "cassandra",
    "clickhouse": "clickhouse",
    "influxdb": "influxdb",
    "neo4j": "neo4j",
}
PRERELEASE_WEIGHTS = {
    "dev": -5,
    "alpha": -4,
    "a": -4,
    "beta": -3,
    "b": -3,
    "pre": -2,
    "preview": -2,
    "rc": -1,
}


def collect_cve_evidence(task: TaskInput) -> list[EvidenceItem]:
    """围绕任务中的 CVE 编号收集高可信证据。"""
    cve_id = task.cve_id.strip().upper()
    if not cve_id:
        return []

    evidence: list[EvidenceItem] = []
    failures: list[str] = []
    total_sources = 0

    total_sources += 1
    nvd_item = _safe_collect(
        lambda: _collect_nvd_evidence(cve_id, task.db_type),
        failures=failures,
    )
    if nvd_item is not None:
        evidence.append(nvd_item)

    for config in _build_html_source_configs(cve_id, task.db_type):
        total_sources += 1
        item = _safe_collect(
            lambda config=config: _collect_html_evidence(
                db_type=task.db_type,
                **config,
            ),
            failures=failures,
        )
        if item is not None:
            evidence.append(item)

    if evidence:
        return evidence

    if failures and len(failures) == total_sources:
        raise RuntimeError(
            f"{cve_id} 的外部证据收集全部失败，疑似网络或站点访问问题："
            + " | ".join(failures[:4])
        )

    raise ValueError(
        f"未搜索到 {cve_id} 的相关外部证据，程序已停止。"
    )


def ensure_database_related_evidence(
    task: TaskInput,
    evidence: list[EvidenceItem],
) -> str:
    """根据已收集证据判断当前 CVE 是否属于数据库漏洞。

    返回值为从证据中识别出的数据库类型；若证据明确不足以支撑“数据库漏洞”这一前提，则直接抛错。
    """
    if not task.cve_id.strip() or not evidence:
        return ""

    inferred_db_type = infer_database_type_from_evidence(evidence)
    if inferred_db_type:
        return inferred_db_type

    raise ValueError(
        f"{task.cve_id.strip().upper()} 的外部证据中未识别出明确的数据库产品信息，"
        "当前任务不按数据库漏洞处理，程序已停止。"
    )


def infer_database_type_from_evidence(evidence: list[EvidenceItem]) -> str:
    """从外部证据中保守识别数据库类型。"""
    blobs: list[str] = []
    for item in evidence:
        if item.title:
            blobs.append(item.title)
        blobs.extend(item.claims[:5])
        if item.snippet:
            blobs.append(item.snippet)

    for blob in blobs:
        normalized = _normalize_database_type(blob)
        if normalized:
            return normalized
    return ""


def _safe_collect(
    collector,
    *,
    failures: list[str] | None = None,
) -> EvidenceItem | None:
    """单个证据源失败时降级跳过，避免中断整轮任务。"""
    try:
        return collector()
    except RuntimeError as exc:
        if failures is not None:
            failures.append(str(exc))
        return None


def _normalize_database_type(value: str) -> str:
    """把证据文本中的数据库名称收敛成稳定标识。"""
    compact = value.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    for alias, canonical in DATABASE_TYPE_ALIASES.items():
        if alias in compact:
            return canonical
    return ""


def _collect_nvd_evidence(cve_id: str, db_type: str) -> EvidenceItem | None:
    """通过 NVD API 拉取单条 CVE 的结构化证据。"""
    url = (
        "https://services.nvd.nist.gov/rest/json/cves/2.0?"
        + parse.urlencode({"cveId": cve_id})
    )
    payload = _fetch_json(url)
    if not isinstance(payload, dict):
        return None

    vulnerabilities = payload.get("vulnerabilities")
    if not isinstance(vulnerabilities, list) or not vulnerabilities:
        return None

    cve = vulnerabilities[0].get("cve")
    if not isinstance(cve, dict):
        return None

    descriptions = cve.get("descriptions") or []
    description_text = ""
    if isinstance(descriptions, list):
        for item in descriptions:
            if not isinstance(item, dict):
                continue
            if item.get("lang") == "en" and isinstance(item.get("value"), str):
                description_text = item["value"].strip()
                break

    references = cve.get("references") or []
    reference_urls: list[str] = []
    if isinstance(references, list):
        for item in references:
            if not isinstance(item, dict):
                continue
            url_value = item.get("url")
            if isinstance(url_value, str) and url_value.strip():
                reference_urls.append(url_value.strip())

    published_at = cve.get("published", "")
    if not isinstance(published_at, str):
        published_at = ""

    claims: list[str] = []
    cpe_matches = _extract_nvd_cpe_matches(cve)
    top_cpe_matches = _pick_top_cpe_matches(cpe_matches, top_n=3)
    if top_cpe_matches:
        claims.append(
            "top3_cpe_json: "
            + json.dumps(
                {"count": len(top_cpe_matches), "items": top_cpe_matches},
                ensure_ascii=False,
            )
        )

    claims.extend(_extract_claims(description_text, db_type))
    if reference_urls:
        claims.append("参考链接：" + ", ".join(reference_urls[:3]))

    return EvidenceItem(
        source_type="nvd_api",
        source_url=url,
        title=f"{cve_id} - NVD",
        published_at=published_at,
        reliability="high",
        snippet=description_text[:800],
        claims=claims,
    )


def _extract_nvd_cpe_matches(cve: dict[str, object]) -> list[dict[str, object]]:
    """从 NVD CVE payload 中递归提取 cpeMatch 条目。"""
    configurations = cve.get("configurations")
    if not isinstance(configurations, list):
        return []

    matches: list[dict[str, object]] = []
    for config in configurations:
        if not isinstance(config, dict):
            continue
        _collect_cpe_matches_from_nodes(config.get("nodes"), matches)
    return matches


def _collect_cpe_matches_from_nodes(
    nodes: object,
    matches: list[dict[str, object]],
) -> None:
    """递归遍历 NVD configuration nodes，收集 cpeMatch。"""
    if not isinstance(nodes, list):
        return

    for node in nodes:
        if not isinstance(node, dict):
            continue

        raw_cpe_matches = node.get("cpeMatch")
        if isinstance(raw_cpe_matches, list):
            for item in raw_cpe_matches:
                if not isinstance(item, dict):
                    continue
                criteria = item.get("criteria")
                if not isinstance(criteria, str) or not criteria.strip():
                    continue

                parsed_cpe = _parse_cpe23(criteria)
                rank_version = _select_rank_version(
                    match=item,
                    cpe_version=parsed_cpe.get("version", ""),
                )
                matches.append(
                    {
                        "criteria": criteria.strip(),
                        "vulnerable": bool(item.get("vulnerable")),
                        "version_start_including": _ensure_version_token(
                            item.get("versionStartIncluding")
                        ),
                        "version_start_excluding": _ensure_version_token(
                            item.get("versionStartExcluding")
                        ),
                        "version_end_including": _ensure_version_token(
                            item.get("versionEndIncluding")
                        ),
                        "version_end_excluding": _ensure_version_token(
                            item.get("versionEndExcluding")
                        ),
                        "rank_version": rank_version,
                        "part": parsed_cpe.get("part", ""),
                        "vendor": parsed_cpe.get("vendor", ""),
                        "product": parsed_cpe.get("product", ""),
                        "version": parsed_cpe.get("version", ""),
                    }
                )

        _collect_cpe_matches_from_nodes(node.get("children"), matches)


def _parse_cpe23(criteria: str) -> dict[str, str]:
    """解析 CPE 2.3 字符串的关键字段。"""
    segments = _split_cpe_criteria(criteria.strip())
    if len(segments) < 6:
        return {"part": "", "vendor": "", "product": "", "version": ""}
    return {
        "part": segments[2],
        "vendor": segments[3],
        "product": segments[4],
        "version": segments[5],
    }


def _split_cpe_criteria(criteria: str) -> list[str]:
    """按未转义冒号拆分 CPE 字符串。"""
    segments: list[str] = []
    current: list[str] = []
    escaped = False
    for char in criteria:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            current.append(char)
            continue
        if char == ":":
            segments.append("".join(current))
            current = []
            continue
        current.append(char)
    segments.append("".join(current))
    return segments


def _select_rank_version(
    *,
    match: dict[str, object],
    cpe_version: str,
) -> str:
    """为排序选择单个 CPE 条目的代表版本。"""
    candidates = [
        _ensure_version_token(match.get("versionEndExcluding")),
        _ensure_version_token(match.get("versionEndIncluding")),
        _ensure_version_token(cpe_version),
        _ensure_version_token(match.get("versionStartExcluding")),
        _ensure_version_token(match.get("versionStartIncluding")),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return ""


def _pick_top_cpe_matches(
    cpe_matches: list[dict[str, object]],
    *,
    top_n: int,
) -> list[dict[str, object]]:
    """选出版本号最高的 top_n 条 CPE 信息，优先保留 vulnerable=true。"""
    valid_matches = [
        item
        for item in cpe_matches
        if _ensure_version_token(item.get("rank_version"))
    ]
    sorted_matches = sorted(
        valid_matches,
        key=lambda item: _version_sort_key(str(item.get("rank_version", ""))),
        reverse=True,
    )
    vulnerable_matches = [
        item for item in sorted_matches if bool(item.get("vulnerable"))
    ]
    if len(vulnerable_matches) >= top_n:
        return vulnerable_matches[:top_n]

    selected = vulnerable_matches[:]
    for item in sorted_matches:
        if bool(item.get("vulnerable")):
            continue
        selected.append(item)
        if len(selected) >= top_n:
            break
    return selected


def _version_sort_key(version: str) -> tuple[object, ...]:
    """把版本字符串转换为可排序键，用于近似比较“新旧”。"""
    normalized = _ensure_version_token(version)
    if not normalized:
        return ()

    epoch = 0
    remainder = normalized
    if ":" in normalized:
        maybe_epoch, maybe_remainder = normalized.split(":", 1)
        if maybe_epoch.isdigit():
            epoch = int(maybe_epoch)
            remainder = maybe_remainder

    remainder = remainder.lower().lstrip("v")
    qualifier_match = re.search(
        r"(?:^|[.\-+_~:])(dev|alpha|a|beta|b|pre|preview|rc)(?:[.\-+_~:]|$|\d)",
        remainder,
    )
    if qualifier_match:
        qualifier = qualifier_match.group(1)
        qualifier_index = qualifier_match.start(1)
        core_text = remainder[:qualifier_index]
        suffix_text = remainder[qualifier_index:]
    else:
        qualifier = ""
        core_text = remainder
        suffix_text = ""

    core_numbers = tuple(int(item) for item in re.findall(r"\d+", core_text))
    suffix_numbers = tuple(int(item) for item in re.findall(r"\d+", suffix_text))
    qualifier_weight = PRERELEASE_WEIGHTS.get(qualifier, 0)
    return (epoch, core_numbers, qualifier_weight, suffix_numbers, remainder)


def _ensure_version_token(value: object) -> str:
    """清洗单个版本 token；空值或通配符返回空字符串。"""
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if not cleaned or cleaned in {"*", "-", "n/a", "N/A"}:
        return ""
    return cleaned


def _build_html_source_configs(cve_id: str, db_type: str) -> list[dict[str, str]]:
    """构造所有 HTML 证据源的统一配置。"""
    configs = [
        {
            "source_type": "debian_tracker",
            "source_url": f"https://security-tracker.debian.org/tracker/{parse.quote(cve_id)}",
            "title": f"{cve_id} - Debian Security Tracker",
            "reliability": "high",
            "required_text": "",
        },
        {
            "source_type": "ubuntu_security",
            "source_url": f"https://ubuntu.com/security/{parse.quote(cve_id)}",
            "title": f"{cve_id} - Ubuntu Security",
            "reliability": "high",
            "required_text": "",
        },
        {
            "source_type": "redhat_cve",
            "source_url": f"https://access.redhat.com/security/cve/{parse.quote(cve_id)}",
            "title": f"{cve_id} - Red Hat CVE Database",
            "reliability": "medium",
            "required_text": "",
        },
        {
            "source_type": "aliyun_avd",
            "source_url": (
                f"https://avd.aliyun.com/nvd/list?keyword={parse.quote(cve_id)}"
            ),
            "title": f"{cve_id} - 阿里云漏洞库",
            "reliability": "medium",
            "required_text": cve_id,
        },
    ]

    return configs


def _collect_html_evidence(
    *,
    source_type: str,
    source_url: str,
    title: str,
    reliability: str,
    db_type: str,
    required_text: str = "",
) -> EvidenceItem | None:
    """抓取 HTML 页面型证据源，并提取可供后续阶段消费的文本摘要。"""
    html = _fetch_text(source_url)
    if not html:
        return None

    text = _html_to_text(html)
    if not text:
        return None
    if required_text and required_text.upper() not in text.upper():
        return None

    snippet = text[:800]
    claims = _extract_claims(text, db_type)
    if not claims:
        claims = [snippet[:200]]

    return EvidenceItem(
        source_type=source_type,
        source_url=source_url,
        title=title,
        published_at="",
        reliability=reliability,
        snippet=snippet,
        claims=claims[:8],
    )


def _extract_claims(text: str, db_type: str) -> list[str]:
    """从页面正文中抽取少量与数据库、版本和构建语义相关的事实句。"""
    if not text:
        return []

    sentences = re.split(r"(?<=[。！？.!?])\s+", text)
    keywords = [
        db_type.strip().lower(),
        "package",
        "debian",
        "ubuntu",
        "red hat",
        "docker",
        "image",
        "lua",
        "module",
        "plugin",
        "configuration",
        "build",
    ]

    claims: list[str] = []
    for sentence in sentences:
        cleaned = " ".join(sentence.split())
        lowered = cleaned.lower()
        if len(cleaned) < 25:
            continue
        if any(keyword and keyword in lowered for keyword in keywords):
            claims.append(cleaned[:240])
        if len(claims) >= 6:
            break
    return claims


def _html_to_text(html: str) -> str:
    """把原始 HTML 粗略清洗成纯文本，便于后续关键词抽取。"""
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_json(url: str) -> dict | None:
    """抓取 JSON 端点并在成功时返回对象字典。"""
    body = _fetch_text(url)
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _fetch_text(url: str) -> str:
    """优先用 urllib 抓取文本，失败时回退到 curl。"""
    try:
        return _fetch_text_with_urllib(url)
    except RuntimeError as exc:
        return _fetch_text_with_curl(url, fallback_reason=str(exc))


def _fetch_text_with_urllib(url: str) -> str:
    """使用 urllib 发起 GET 请求并返回文本内容。"""
    req = request.Request(
        url,
        headers={
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "User-Agent": "db-env-gc/0.3",
            "Connection": "close",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="ignore")
    except error.HTTPError as exc:
        if exc.code == 404:
            return ""
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def _fetch_text_with_curl(url: str, *, fallback_reason: str) -> str:
    """在 urllib 失败时使用 curl 做兜底抓取。"""
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--header",
        "User-Agent: db-env-gc/0.3",
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

    if completed.returncode != 0:
        raise RuntimeError(
            f"{fallback_reason}; curl fallback failed: {completed.stderr.strip()}"
        )
    return completed.stdout
