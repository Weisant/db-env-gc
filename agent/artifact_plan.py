"""受控 ReAct 风格的制品计划生成器。"""

from __future__ import annotations

import json
from typing import Any

from agent.llm import JsonChatClient
from agent.models import ArtifactFact, ArtifactPlan, ReproductionProfile, TaskInput
from agent.prompt_loader import load_prompt
from agent.runtime.payload_builders import (
    build_artifact_fact_summary,
    build_profile_summary,
)
from tools.registry_tools import resolve_image_source
from tools.version_source_tools import resolve_version_source


MAX_REACT_STEPS = 3


def build_artifact_plan(
    task: TaskInput,
    reproduction_profile: ReproductionProfile,
    client: JsonChatClient,
) -> tuple[ArtifactPlan, list[ArtifactFact], list[dict[str, Any]]]:
    """通过小 ReAct 循环生成制品计划（LLM 主导，代码仅做候选循环执行）。"""
    system_prompt = load_prompt("artifact_plan.md")
    effective_db_type = _ensure_string(reproduction_profile.evidence_db_type) or _ensure_string(
        task.db_type
    )
    candidate_versions = _extract_version_candidates(reproduction_profile)
    selected_version = reproduction_profile.version_policy.requested_version.strip()
    if not selected_version and candidate_versions:
        selected_version = candidate_versions[0]
    version_source = (
        "constraints" if candidate_versions and selected_version in candidate_versions else "requested"
    )
    candidate_cursor = _find_candidate_index(candidate_versions, selected_version)
    if candidate_cursor < 0 and candidate_versions:
        candidate_cursor = 0
        selected_version = candidate_versions[0]
        version_source = "constraints"

    route_action = ""
    facts: list[ArtifactFact] = []
    trace: list[dict[str, Any]] = []
    last_response: dict[str, Any] = {}
    react_steps = max(
        MAX_REACT_STEPS,
        len(candidate_versions) + 2 if candidate_versions else MAX_REACT_STEPS,
    )

    for step_index in range(1, react_steps + 1):
        if not selected_version and 0 <= candidate_cursor < len(candidate_versions):
            selected_version = candidate_versions[candidate_cursor]
            version_source = "constraints"

        user_prompt = _build_react_user_prompt(
            reproduction_profile=reproduction_profile,
            selected_version=selected_version,
            version_source=version_source,
            effective_db_type=effective_db_type,
            facts=facts,
            trace=trace,
            step_index=step_index,
            candidate_versions=candidate_versions,
            route_action=route_action,
        )
        response = client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0,
            model=client.settings.planner_model,
        )
        last_response = response if isinstance(response, dict) else {}

        thought = _ensure_string(response.get("thought"))
        model_selected_version = _ensure_string(response.get("selected_version"))
        if model_selected_version:
            selected_version = model_selected_version
        cursor_from_model = _find_candidate_index(candidate_versions, selected_version)
        if cursor_from_model >= 0:
            candidate_cursor = cursor_from_model
            version_source = "constraints"

        model_version_source = _ensure_string(response.get("version_source"))
        if model_version_source:
            version_source = model_version_source

        requested_action = _ensure_string(response.get("next_action"))
        if requested_action in {"check_image", "check_source"}:
            if not route_action:
                route_action = requested_action
            elif requested_action != route_action:
                requested_action = route_action
        next_action = requested_action or (route_action if route_action else "finish")
        if (
            route_action
            and next_action == "finish"
            and _should_continue_candidate_probe(
                candidate_versions=candidate_versions,
                candidate_cursor=candidate_cursor,
                selected_version=selected_version,
                facts=facts,
            )
        ):
            next_action = route_action

        trace_entry: dict[str, Any] = {
            "step": step_index,
            "thought": thought,
            "effective_db_type": effective_db_type,
            "selected_version": selected_version,
            "version_source": version_source,
            "requested_action": requested_action,
            "next_action": next_action,
        }
        if route_action:
            trace_entry["route_action"] = route_action

        if next_action == "check_image":
            fact = _probe_image_fact(task, effective_db_type, selected_version)
            _upsert_fact(facts, fact)
            trace_entry["observation"] = fact.to_dict()
            next_candidate, next_cursor = _next_candidate_after(
                candidate_versions,
                candidate_cursor,
            )
            if not fact.available and next_candidate:
                candidate_cursor = next_cursor
                selected_version = next_candidate
                version_source = "constraints"
                trace_entry["candidate_switch_reason"] = "当前候选探测失败，切换到下一个候选版本。"
                trace_entry["candidate_switch_to"] = next_candidate
            trace.append(trace_entry)
            continue

        if next_action == "check_source":
            fact = _probe_source_fact(task, effective_db_type, selected_version)
            _upsert_fact(facts, fact)
            trace_entry["observation"] = fact.to_dict()
            next_candidate, next_cursor = _next_candidate_after(
                candidate_versions,
                candidate_cursor,
            )
            if not fact.available and next_candidate:
                candidate_cursor = next_cursor
                selected_version = next_candidate
                version_source = "constraints"
                trace_entry["candidate_switch_reason"] = "当前候选探测失败，切换到下一个候选版本。"
                trace_entry["candidate_switch_to"] = next_candidate
            trace.append(trace_entry)
            continue

        trace_entry["observation"] = {
            "message": "根据当前画像和事实进入收束阶段。"
        }
        trace.append(trace_entry)
        return _finalize_plan(
            response=last_response,
            effective_db_type=effective_db_type,
            selected_version=selected_version,
            version_source=version_source,
        ), facts, trace

    return _finalize_plan(
        response=last_response,
        effective_db_type=effective_db_type,
        selected_version=selected_version,
        version_source=version_source,
    ), facts, trace


def _build_react_user_prompt(
    *,
    reproduction_profile: ReproductionProfile,
    selected_version: str,
    version_source: str,
    effective_db_type: str,
    facts: list[ArtifactFact],
    trace: list[dict[str, Any]],
    step_index: int,
    candidate_versions: list[str],
    route_action: str,
) -> str:
    """构造单轮 ReAct 输入。"""
    return (
        "请根据当前轮次上下文输出下一步 JSON。\n\n"
        f"当前轮次：{step_index}\n\n"
        "复现画像：\n"
        f"{json.dumps(build_profile_summary(reproduction_profile), ensure_ascii=False, indent=2)}\n\n"
        "补齐后的数据库类型：\n"
        f"{json.dumps({'effective_db_type': effective_db_type}, ensure_ascii=False, indent=2)}\n\n"
        "当前已选版本：\n"
        f"{json.dumps({'selected_version': selected_version, 'version_source': version_source}, ensure_ascii=False, indent=2)}\n\n"
        "候选版本队列（按优先探测顺序）：\n"
        f"{json.dumps({'candidate_versions': candidate_versions}, ensure_ascii=False, indent=2)}\n\n"
        "当前固定探测路线（为空表示尚未确定）：\n"
        f"{json.dumps({'route_action': route_action}, ensure_ascii=False, indent=2)}\n\n"
        "已收集的制品事实：\n"
        f"{json.dumps(build_artifact_fact_summary(facts, limit=12), ensure_ascii=False, indent=2)}\n\n"
        "历史轨迹：\n"
        f"{json.dumps(trace, ensure_ascii=False, indent=2)}"
    )


def _probe_image_fact(task: TaskInput, effective_db_type: str, version: str) -> ArtifactFact:
    """查询指定版本的 Docker Hub 精确 tag 是否存在。"""
    version_task = _build_version_task(task, effective_db_type, version)
    image_resolution = resolve_image_source(version_task)
    return ArtifactFact(
        fact_type="dockerhub_tag",
        source="docker_hub",
        identifier=_build_image_identifier(image_resolution, effective_db_type),
        version=version,
        ref=image_resolution.image_ref,
        available=image_resolution.availability == "tag_found",
        notes=image_resolution.notes[:3],
    )


def _probe_source_fact(task: TaskInput, effective_db_type: str, version: str) -> ArtifactFact:
    """查询指定版本的源码下载地址是否存在。"""
    version_task = _build_version_task(task, effective_db_type, version)
    version_resolution = resolve_version_source(version_task)
    return ArtifactFact(
        fact_type="source_release",
        source=version_resolution.source_name or "official_source",
        identifier=effective_db_type,
        version=version,
        ref=version_resolution.matched_url,
        available=version_resolution.version_exists,
        notes=version_resolution.notes[:3],
    )


def _upsert_fact(facts: list[ArtifactFact], fact: ArtifactFact) -> None:
    """用最新 observation 覆盖同类型同版本事实。"""
    for index, item in enumerate(facts):
        if item.fact_type == fact.fact_type and item.version == fact.version:
            facts[index] = fact
            return
    facts.append(fact)


def _finalize_plan(
    *,
    response: dict[str, Any],
    effective_db_type: str,
    selected_version: str,
    version_source: str,
) -> ArtifactPlan:
    """直接把 LLM 的 finish_plan 收束为 ArtifactPlan。"""
    raw_plan = response.get("finish_plan")
    raw_plan = raw_plan if isinstance(raw_plan, dict) else {}

    return ArtifactPlan(
        project_name=_ensure_string(raw_plan.get("project_name")),
        effective_db_type=effective_db_type,
        delivery_strategy=_ensure_string(raw_plan.get("delivery_strategy")),
        primary_artifact_kind=_ensure_string(raw_plan.get("primary_artifact_kind")),
        selected_version=selected_version,
        version_source=version_source,
        selected_identifier=_ensure_string(raw_plan.get("selected_identifier")),
        selected_image=_ensure_string(raw_plan.get("selected_image")),
        selected_download_url=_ensure_string(raw_plan.get("selected_download_url")),
        requires_dockerfile=bool(raw_plan.get("requires_dockerfile")),
        reason=_ensure_string(raw_plan.get("reason")) or _ensure_string(response.get("reason")),
        confidence=_ensure_string(raw_plan.get("confidence")) or _ensure_string(
            response.get("confidence")
        ),
        notes=_ensure_list_of_str(raw_plan.get("notes"), "artifact_plan.notes"),
    )


def _build_version_task(task: TaskInput, effective_db_type: str, version: str) -> TaskInput:
    """为单个候选版本构造临时任务对象。"""
    return TaskInput(
        cve_id=task.cve_id,
        db_type=effective_db_type,
        version=version,
        port=task.port,
        database=task.database,
        username=task.username,
        password=task.password,
        root_password=task.root_password,
        project_name=task.project_name,
        config=task.config,
        notes=task.notes,
        raw_request=task.raw_request,
        requested_version=task.requested_version or task.version,
        effective_version=version,
    )


def _build_image_identifier(image_resolution, db_type: str) -> str:
    """把镜像解析结果转成易读的仓库标识。"""
    if image_resolution.repository:
        if image_resolution.namespace and image_resolution.namespace != "library":
            return f"{image_resolution.namespace}/{image_resolution.repository}"
        return image_resolution.repository
    return db_type


def _ensure_string(value: Any) -> str:
    """把任意值规范成去空白字符串。"""
    if value is None:
        return ""
    return str(value).strip()


def _ensure_list_of_str(value: Any, field_name: str) -> list[str]:
    """就地实现一个轻量字符串列表规范化。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return [str(item).strip() for item in value if str(item).strip()]


def _extract_version_candidates(reproduction_profile: ReproductionProfile) -> list[str]:
    """从画像 notes 中提取顺序候选版本。"""
    candidates: list[str] = []
    for note in reproduction_profile.version_policy.notes:
        parsed = _parse_json_note(note, prefix="version_candidates_json")
        if not isinstance(parsed, dict):
            continue
        raw_candidates = parsed.get("candidates")
        if not isinstance(raw_candidates, list):
            continue
        for item in raw_candidates:
            if isinstance(item, str):
                token = item.strip()
            elif isinstance(item, dict):
                token = _ensure_string(item.get("version"))
            else:
                token = ""
            if token:
                candidates.append(token)

    requested_version = reproduction_profile.version_policy.requested_version.strip()
    if requested_version:
        candidates.insert(0, requested_version)
    return _unique_non_empty(candidates)


def _parse_json_note(note: str, *, prefix: str) -> dict[str, Any] | None:
    """解析类似 `prefix: {...}` 的结构化 note。"""
    for delimiter in (":", "："):
        marker = f"{prefix}{delimiter}"
        if not note.startswith(marker):
            continue
        payload = note[len(marker) :].strip()
        if not payload:
            return None
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _next_candidate_after(
    candidate_versions: list[str],
    candidate_cursor: int,
) -> tuple[str, int]:
    """返回当前游标之后的下一个候选版本。"""
    next_cursor = candidate_cursor + 1
    if next_cursor < 0 or next_cursor >= len(candidate_versions):
        return "", candidate_cursor
    return candidate_versions[next_cursor], next_cursor


def _find_candidate_index(candidate_versions: list[str], version: str) -> int:
    """返回版本在候选列表中的下标，不存在返回 -1。"""
    if not version:
        return -1
    try:
        return candidate_versions.index(version)
    except ValueError:
        return -1


def _should_continue_candidate_probe(
    *,
    candidate_versions: list[str],
    candidate_cursor: int,
    selected_version: str,
    facts: list[ArtifactFact],
) -> bool:
    """当当前候选尚未探测成功且后续仍有候选时，继续探测而不是直接收束。"""
    if not candidate_versions or candidate_cursor < 0:
        return False
    if any(item.version == selected_version and item.available for item in facts):
        return False
    return candidate_cursor + 1 < len(candidate_versions)


def _unique_non_empty(items: list[str]) -> list[str]:
    """按顺序去重，过滤空白项。"""
    unique_items: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in unique_items:
            unique_items.append(cleaned)
    return unique_items
