"""LLM 驱动的项目校验器。

这个模块现在同时承担两件事情：
1. 校验已经写到磁盘上的真实项目文件
2. 如果发现可自动修复的问题，则直接调用 tools 覆盖文件

也就是说，原来的独立修复能力被并入了 validator 模块内部，
对外部主流程来说，它仍然只表现为一个“validator 阶段”。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent.llm import JsonChatClient
from agent.models import (
    EnvSpec,
    ProjectArtifacts,
    ProjectSnapshot,
    ResolvedTask,
    TaskInput,
    ValidationReport,
)
from agent.runtime.payload_builders import (
    build_runtime_snapshot_summary,
    build_runtime_task_summary,
)
from agent.prompt_loader import load_prompt
from tools import overwrite_project_files, read_project_snapshot


def validate_project(
    task: TaskInput,
    resolved_task: ResolvedTask,
    reproduction_profile,
    artifact_plan,
    env_spec: EnvSpec,
    artifacts: ProjectArtifacts,
    run_dir: Path,
    client: JsonChatClient,
) -> tuple[ValidationReport, ProjectArtifacts, bool]:
    """校验真实项目，并在必要时执行自动修复。

    返回值依次为：
    1. 最终校验报告
    2. 当前最新的项目文件集合
    3. 本轮是否发生过自动修复
    """
    initial_snapshot = read_project_snapshot(run_dir)
    initial_report = _validate_runtime_project(
        task=task,
        resolved_task=resolved_task,
        env_spec=env_spec,
        snapshot=initial_snapshot,
        client=client,
    )

    # 只有结构性问题才触发自动修复。
    # warnings 和轻微格式问题只保留在报告中，不额外拉起修复调用。
    should_repair = should_auto_repair(initial_report)
    if not should_repair:
        return initial_report, artifacts, False

    repaired_artifacts = _run_repair(
        task,
        resolved_task,
        reproduction_profile,
        artifact_plan,
        env_spec,
        initial_snapshot,
        initial_report,
        client,
    )
    repaired_artifacts.project_name = resolved_task.project_name
    overwrite_project_files(run_dir, repaired_artifacts.files)

    # 修复后重新读取磁盘快照，确保复检看到的是真实最终结果。
    repaired_snapshot = read_project_snapshot(run_dir)
    final_report = _run_local_runtime_precheck(
        task=task,
        resolved_task=resolved_task,
        env_spec=env_spec,
        snapshot=repaired_snapshot,
    )
    return final_report, repaired_artifacts, True


def _validate_runtime_project(
    task: TaskInput,
    resolved_task: ResolvedTask,
    env_spec: EnvSpec,
    snapshot: ProjectSnapshot,
    client: JsonChatClient,
) -> ValidationReport:
    """先做最小本地存在性检查，再让 LLM 检查文件内容问题。"""
    local_report = _run_local_runtime_precheck(
        task=task,
        resolved_task=resolved_task,
        env_spec=env_spec,
        snapshot=snapshot,
    )
    if local_report.findings:
        return local_report

    llm_report = _run_validation(
        task=task,
        resolved_task=resolved_task,
        env_spec=env_spec,
        snapshot=snapshot,
        client=client,
    )
    return _merge_validation_reports(local_report, llm_report)


def _run_validation(
    task: TaskInput,
    resolved_task: ResolvedTask,
    env_spec: EnvSpec,
    snapshot: ProjectSnapshot,
    client: JsonChatClient,
) -> ValidationReport:
    """执行一次直接检查文件内容问题的轻量校验调用。"""
    system_prompt = load_prompt("validator.md")
    user_prompt = (
        "本地预检查已经完成了必需文件存在性和本地文件引用存在性检查。\n"
        "请直接检查下面这些 Docker 项目文件中的代码和配置是否存在问题，"
        "重点关注 compose、Dockerfile、env、README 之间是否有错误、冲突或明显不合理之处。\n\n"
        "运行任务摘要：\n"
        f"{json.dumps(build_runtime_task_summary(task, resolved_task, env_spec), ensure_ascii=False, indent=2)}\n\n"
        "真实磁盘项目快照摘要：\n"
        f"{json.dumps(build_runtime_snapshot_summary(snapshot), ensure_ascii=False, indent=2)}"
    )
    response = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0,
        model=client.settings.validator_model,
    )
    return ValidationReport.from_dict(response)


def _run_repair(
    task: TaskInput,
    resolved_task: ResolvedTask,
    reproduction_profile,
    artifact_plan,
    env_spec: EnvSpec,
    snapshot: ProjectSnapshot,
    validation: ValidationReport,
    client: JsonChatClient,
) -> ProjectArtifacts:
    """在 validator 内部执行修复子步骤。

    这里仍然使用独立提示词文件，是为了把“校验”和“修复”两个子任务分开约束，
    但从系统架构上看，它们都属于 validator 阶段的一部分。
    """
    system_prompt = load_prompt("validator_repair.md")
    user_prompt = (
        "本地预检查已经完成了必需文件存在性和本地文件引用存在性检查。\n"
        "请根据下面的校验报告修复数据库 Docker 项目文件中的代码和配置问题，并输出修复后的完整文件集合 JSON。\n\n"
        "运行任务摘要：\n"
        f"{json.dumps(build_runtime_task_summary(task, resolved_task, env_spec), ensure_ascii=False, indent=2)}\n\n"
        "真实磁盘项目快照摘要：\n"
        f"{json.dumps(build_runtime_snapshot_summary(snapshot), ensure_ascii=False, indent=2)}\n\n"
        "校验报告：\n"
        f"{json.dumps(validation.to_dict(), ensure_ascii=False, indent=2)}"
    )
    response = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        model=client.settings.validator_model,
    )
    return ProjectArtifacts.from_dict(response)


def _run_local_runtime_precheck(
    task: TaskInput,
    resolved_task: ResolvedTask,
    env_spec: EnvSpec,
    snapshot: ProjectSnapshot,
) -> ValidationReport:
    """用最小确定性规则检查必需文件与本地文件引用是否存在。"""
    file_map = {item.path: item.content for item in snapshot.files}
    findings: list[str] = []
    warnings: list[str] = []
    repair_instructions: list[str] = []

    compose_path = _find_first_existing_path(
        file_map,
        ["docker-compose.yml", "compose.yml", "compose.yaml"],
    )
    compose_content = file_map.get(compose_path, "") if compose_path else ""
    dockerfile_content = file_map.get("Dockerfile", "")
    env_example_content = file_map.get(".env.example", "")
    readme_content = file_map.get("README.md", "")

    if not compose_path:
        findings.append("缺少 docker-compose 配置文件，项目无法直接通过 Docker Compose 启动。")
        repair_instructions.append("补充 docker-compose.yml，并定义至少一个数据库服务。")
    if ".env.example" not in file_map:
        findings.append("缺少 .env.example，项目缺少基础环境变量示例文件。")
        repair_instructions.append("补充 .env.example，并为 compose 中引用的环境变量提供默认示例值。")
    if "README.md" not in file_map:
        warnings.append("缺少 README.md，项目可运行性不一定受影响，但交付说明不完整。")

    if env_spec.requires_dockerfile and "Dockerfile" not in file_map:
        findings.append("环境规划要求存在 Dockerfile，但当前项目缺少 Dockerfile。")
        repair_instructions.append("补充 Dockerfile，并确保 compose 通过 build 使用它。")

    if compose_content:
        custom_dockerfile = _extract_compose_dockerfile_path(compose_content)
        if custom_dockerfile and custom_dockerfile not in file_map:
            findings.append(
                f"docker-compose 指定了 Dockerfile 路径 {custom_dockerfile}，但该文件不存在。"
            )
            repair_instructions.append(
                f"补充 {custom_dockerfile}，或把 compose 中的 dockerfile 路径改成存在的文件。"
            )

    if dockerfile_content:
        missing_copy_sources = _find_missing_copy_sources(dockerfile_content, file_map)
        if missing_copy_sources:
            findings.append(
                "Dockerfile 引用了不存在的本地文件："
                + ", ".join(sorted(missing_copy_sources))
                + "。"
            )
            repair_instructions.append(
                "补充 Dockerfile 中 COPY/ADD 引用的文件，或移除无效引用。"
            )

    findings = _unique_list(findings)
    warnings = _unique_list(warnings)
    repair_instructions = _unique_list(repair_instructions)
    return ValidationReport(
        passed=not findings,
        findings=findings,
        warnings=warnings,
        repair_instructions=repair_instructions,
    )


def _merge_validation_reports(
    local_report: ValidationReport,
    llm_report: ValidationReport,
) -> ValidationReport:
    """合并本地预检查与轻量 LLM 校验结果。"""
    findings = _unique_list(local_report.findings + llm_report.findings)
    warnings = _unique_list(local_report.warnings + llm_report.warnings)
    repairs = _unique_list(local_report.repair_instructions + llm_report.repair_instructions)
    return ValidationReport(
        passed=not findings,
        findings=findings,
        warnings=warnings,
        repair_instructions=repairs,
    )


def should_auto_repair(validation: ValidationReport) -> bool:
    """判断当前报告是否值得进入自动修复闭环。

    这里不再做关键词启发式推断，只保留最小控制：
    - 没有 findings 不修
    - 没有 repair_instructions 不修
    - 其余交给 validator 报告自身决定
    """
    return bool(validation.findings and validation.repair_instructions)

def _find_first_existing_path(
    file_map: dict[str, str],
    candidates: list[str],
) -> str:
    """返回候选路径中第一个真实存在的文件。"""
    for candidate in candidates:
        if candidate in file_map:
            return candidate
    return ""

def _extract_compose_dockerfile_path(compose_content: str) -> str:
    """从 compose 文本里提取自定义 dockerfile 路径。"""
    match = re.search(r"(?m)^\s*dockerfile\s*:\s*([^\s#]+)", compose_content)
    if not match:
        return ""
    return match.group(1).strip().lstrip("./")



def _find_missing_copy_sources(
    dockerfile_content: str,
    file_map: dict[str, str],
) -> list[str]:
    """找出 Dockerfile 中引用但本地缺失的 COPY/ADD 源文件。"""
    missing_sources: list[str] = []
    for raw_line in dockerfile_content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        upper_line = line.upper()
        if not (upper_line.startswith("COPY ") or upper_line.startswith("ADD ")):
            continue
        if "--from=" in line:
            continue
        sources = _extract_copy_sources_from_line(line)
        for source in sources:
            normalized = source.strip().lstrip("./")
            if (
                not normalized
                or normalized == "."
                or normalized.startswith("http://")
                or normalized.startswith("https://")
                or "*" in normalized
            ):
                continue
            if normalized not in file_map:
                missing_sources.append(normalized)
    return _unique_list(missing_sources)


def _extract_copy_sources_from_line(line: str) -> list[str]:
    """从单条 COPY/ADD 指令中解析源路径列表。"""
    instruction = line.split(None, 1)
    if len(instruction) < 2:
        return []
    payload = instruction[1].strip()
    if payload.startswith("["):
        try:
            items = json.loads(payload)
        except json.JSONDecodeError:
            return []
        if not isinstance(items, list) or len(items) < 2:
            return []
        return [str(item).strip() for item in items[:-1]]

    tokens = payload.split()
    filtered_tokens = [token for token in tokens if not token.startswith("--")]
    if len(filtered_tokens) < 2:
        return []
    return filtered_tokens[:-1]


def _unique_list(items: list[str]) -> list[str]:
    """按原顺序去重，并过滤空白项。"""
    unique_items: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in unique_items:
            unique_items.append(cleaned)
    return unique_items
