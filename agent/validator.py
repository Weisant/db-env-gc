"""LLM 驱动的项目校验器。

这个模块现在同时承担两件事情：
1. 校验已经写到磁盘上的真实项目文件
2. 如果发现可自动修复的问题，则直接调用 tools 覆盖文件

也就是说，原来的 repair agent 能力被并入了 validator 模块内部，
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

    # 只要存在关键问题，或 validator 明确给出了修复指令，就触发修复闭环。
    should_repair = bool(initial_report.findings or initial_report.repair_instructions)
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
    system_prompt = load_prompt("repair.md")
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
    )
    return ProjectArtifacts.from_dict(response)
