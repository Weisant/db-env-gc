"""复现约束画像解析器。"""

from __future__ import annotations

import json

from agent.llm import JsonChatClient
from agent.models import (
    EvidenceItem,
    ReproductionProfile,
    TaskInput,
    VersionPolicy,
)
from agent.prompt_loader import load_prompt


def resolve_reproduction_profile(
    task: TaskInput,
    evidence: list[EvidenceItem],
    client: JsonChatClient,
) -> ReproductionProfile:
    """根据任务与外部证据生成复现约束画像。"""
    if not task.cve_id.strip():
        profile = _build_default_profile(task)
        return profile

    system_prompt = load_prompt("reproduction_profile.md")
    user_prompt = (
        "请根据下面的标准化任务和外部证据，输出证据驱动的复现约束画像 JSON。\n\n"
        "标准化任务：\n"
        f"{json.dumps(_build_task_summary(task), ensure_ascii=False, indent=2)}\n\n"
        "外部证据：\n"
        f"{json.dumps(_build_evidence_summary(evidence), ensure_ascii=False, indent=2)}"
    )
    response = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0,
        model=client.settings.planner_model,
    )
    profile = ReproductionProfile.from_dict(response)
    _apply_evidence_priority(profile, task)
    if not profile.required_artifacts:
        profile = _build_default_profile(
            task,
            notes=["模型未返回制品要求，已回退到默认画像。"],
        )
    return profile


def _build_task_summary(task: TaskInput) -> dict[str, object]:
    """提取画像阶段真正需要的紧凑任务摘要。"""
    return _compact_dict(
        {
            "cve_id": task.cve_id,
            "raw_request": task.raw_request,
            "user_explicit_inputs": _compact_dict(
                {
                    "port": task.port,
                    "database": task.database,
                    "username": task.username,
                    "password": task.password,
                    "root_password": task.root_password,
                    "config": task.config,
                }
            ),
            "parser_inference": _compact_dict(
                {
                    "tentative_db_type": task.db_type,
                    "tentative_version": task.requested_version or task.version,
                    "tentative_notes": task.notes[:3],
                }
            ),
        }
    )


def _build_evidence_summary(evidence: list[EvidenceItem]) -> list[dict[str, object]]:
    """把原始证据裁剪成适合送给 LLM 的摘要。"""
    summarized_items: list[dict[str, object]] = []
    for item in evidence[:6]:
        summarized_items.append(
            _compact_dict(
                {
                    "source_type": item.source_type,
                    "title": item.title,
                    "source_url": item.source_url,
                    "published_at": item.published_at,
                    "reliability": item.reliability,
                    "claims": item.claims[:3],
                    "snippet": item.snippet[:280],
                }
            )
        )
    return summarized_items


def _build_default_profile(
    task: TaskInput,
    *,
    notes: list[str] | None = None,
) -> ReproductionProfile:
    """在无证据或模型异常时构造保守默认画像。"""
    notes = notes or []
    return ReproductionProfile(
        cve_id=task.cve_id,
        confidence="medium" if task.cve_id else "high",
        evidence_db_type="",
        evidence_version_scope="",
        input_conflict_detected=False,
        input_conflict_reason="",
        artifact_semantics="unknown",
        requires_build_time_configuration=False,
        version_policy=VersionPolicy(
            requested_version=task.requested_version or task.version,
            min_version="",
            max_version="",
            fixed_versions=[],
            excluded_versions=[],
            notes=["若无额外证据约束，仅保留用户请求版本作为输入事实，不在画像阶段拍板最终版本。"],
        ),
        required_artifacts=[],
        capability_constraints=[],
        required_configuration=task.config,
        required_setup_steps=[],
        forbidden_choices=[],
        open_questions=[],
        notes=notes,
    )


def _compact_dict(data: dict[str, object]) -> dict[str, object]:
    """删除空字段，减少无意义上下文。"""
    compacted: dict[str, object] = {}
    for key, value in data.items():
        if value in ("", [], {}, None):
            continue
        compacted[key] = value
    return compacted


def _apply_evidence_priority(
    profile: ReproductionProfile,
    task: TaskInput,
) -> None:
    """规范化画像字段，并在必要时把用户输入整合进画像。"""
    explicit_evidence_db_type = _normalize_db_type_token(profile.evidence_db_type)
    normalized_task_db_type = _normalize_db_type_token(task.db_type)
    if explicit_evidence_db_type:
        profile.evidence_db_type = explicit_evidence_db_type
    elif normalized_task_db_type:
        profile.evidence_db_type = normalized_task_db_type
        profile.notes = _unique_list(
            profile.notes
            + [f"外部证据未明确数据库类型，画像暂使用用户输入数据库类型 {normalized_task_db_type}。"]
        )
    else:
        profile.evidence_db_type = profile.evidence_db_type.strip()
    profile.evidence_version_scope = profile.evidence_version_scope.strip()
    if not profile.version_policy.requested_version.strip():
        requested_version = (task.requested_version or task.version).strip()
        profile.version_policy.requested_version = requested_version
        if requested_version:
            profile.notes = _unique_list(
                profile.notes + [f"外部证据未明确目标版本，画像暂使用用户输入版本 {requested_version}。"]
            )

    parser_db_type = _normalize_db_type_token(task.db_type)
    conflict_detected = bool(
        explicit_evidence_db_type
        and parser_db_type
        and explicit_evidence_db_type != parser_db_type
    )
    if conflict_detected:
        profile.input_conflict_detected = True
        profile.input_conflict_reason = (
            f"外部证据指向 {explicit_evidence_db_type}，但 parser 暂定为 {parser_db_type}。"
        )
        profile.confidence = "low"
        profile.notes = _unique_list(
            profile.notes + [profile.input_conflict_reason, "画像阶段应优先保留外部证据识别结果。"]
        )
        profile.forbidden_choices = _unique_list(
            profile.forbidden_choices
            + [f"继续沿用 parser 暂定的数据库类型 {parser_db_type}。"]
        )


def _normalize_db_type_candidate(value: str) -> str:
    """把证据文本中的数据库描述收敛成稳定标识。"""
    text = value.strip().lower()
    compact = text.replace(" ", "").replace("_", "").replace("-", "")
    alias_map = {
        "postgresql": "postgres",
        "postgres": "postgres",
        "redis": "redis",
        "mysql": "mysql",
        "mariadb": "mariadb",
        "mongodb": "mongo",
        "mongo": "mongo",
    }
    for alias, canonical in alias_map.items():
        if alias in compact:
            return canonical
    return ""


def _normalize_db_type_token(value: str) -> str:
    """统一数据库类型 token，便于比较。"""
    return _normalize_db_type_candidate(value)


def _unique_list(items: list[str]) -> list[str]:
    """按原顺序去重，并过滤空白项。"""
    unique_items: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in unique_items:
            unique_items.append(cleaned)
    return unique_items
