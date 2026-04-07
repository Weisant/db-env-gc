"""LLM 驱动的项目校验器。

这个模块现在同时承担两件事情：
1. 校验已经写到磁盘上的真实项目文件
2. 如果发现可自动修复的问题，则直接调用 tools 覆盖文件

也就是说，原来的独立修复能力被并入了 validator 模块内部，
对外部主流程来说，它仍然只表现为一个“validator 阶段”。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.llm import JsonChatClient
from agent.models import EnvSpec, ProjectArtifacts, ProjectSnapshot, TaskInput, ValidationReport
from agent.prompt_loader import load_prompt
from agent.tools import overwrite_project_files, read_project_snapshot


def validate_project(
    task: TaskInput,
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
    initial_report = _run_validation(task, env_spec, initial_snapshot, client)

    # 只有结构性问题才触发自动修复。
    # warnings 和轻微格式问题只保留在报告中，不额外拉起修复调用。
    should_repair = should_auto_repair(initial_report)
    if not should_repair:
        return initial_report, artifacts, False

    repaired_artifacts = _run_repair(task, env_spec, initial_snapshot, initial_report, client)
    overwrite_project_files(run_dir, repaired_artifacts.files)

    # 修复后重新读取磁盘快照，确保复检看到的是真实最终结果。
    repaired_snapshot = read_project_snapshot(run_dir)
    final_report = _run_validation(task, env_spec, repaired_snapshot, client)
    return final_report, repaired_artifacts, True


def _run_validation(
    task: TaskInput,
    env_spec: EnvSpec,
    snapshot: ProjectSnapshot,
    client: JsonChatClient,
) -> ValidationReport:
    """执行一次纯校验调用。"""
    system_prompt = load_prompt("validator.md")
    user_prompt = (
        "请检查下面的数据库 Docker 项目是否完整、自洽、可交付。\n\n"
        "标准化任务：\n"
        f"{json.dumps(task.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "环境规划：\n"
        f"{json.dumps(env_spec.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "真实磁盘项目快照：\n"
        f"{json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2)}"
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
        "请根据下面的校验报告修复数据库 Docker 项目，并输出修复后的完整文件集合 JSON。\n\n"
        "标准化任务：\n"
        f"{json.dumps(task.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "环境规划：\n"
        f"{json.dumps(env_spec.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "真实磁盘项目快照：\n"
        f"{json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2)}\n\n"
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


def should_auto_repair(validation: ValidationReport) -> bool:
    """判断当前报告是否值得进入自动修复闭环。

    目标是减少额外耗时：
    - `warnings` 一律只报告
    - README/Markdown/排版类轻微问题不自动修
    - 只有会影响完整性、关键配置一致性或可运行性的结构性问题才修
    """
    if not validation.findings:
        return False

    structural_keywords = (
        "缺失",
        "缺少",
        "不存在",
        "未生成",
        "不可运行",
        "无法启动",
        "不一致",
        "services",
        "image",
        "ports",
        "docker-compose",
        "端口",
        "镜像",
        "数据库类型",
        "数据库名",
        "用户名",
        "密码",
        "config",
        "init",
    )
    formatting_keywords = (
        "markdown",
        "readme 排版",
        "格式",
        "代码块",
        "缩进",
        "空行",
    )

    for finding in validation.findings:
        lowered = finding.lower()
        if any(keyword in lowered for keyword in formatting_keywords):
            continue
        if any(keyword.lower() in lowered for keyword in structural_keywords):
            return True

    # 即使模型给了 repair_instructions，也先以 findings 的严重程度为准，
    # 避免轻微问题触发额外一轮大模型修复。
    return False
