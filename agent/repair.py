"""LLM 驱动的修复器。"""

from __future__ import annotations

import json

from agent.llm import JsonChatClient
from agent.models import EnvSpec, ProjectArtifacts, TaskInput, ValidationReport
from agent.prompt_loader import load_prompt


def repair_project(
    task: TaskInput,
    env_spec: EnvSpec,
    artifacts: ProjectArtifacts,
    validation: ValidationReport,
    client: JsonChatClient,
) -> ProjectArtifacts:
    """根据校验报告让 LLM 修复完整项目文件集合。"""
    system_prompt = load_prompt("repair.md")
    user_prompt = (
        "请根据校验报告修复下面的项目文件集合，并输出修复后的完整 JSON。\n\n"
        "标准化任务：\n"
        f"{json.dumps(task.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "环境规划：\n"
        f"{json.dumps(env_spec.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "当前项目文件集合：\n"
        f"{json.dumps(artifacts.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "校验报告：\n"
        f"{json.dumps(validation.to_dict(), ensure_ascii=False, indent=2)}"
    )
    response = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
    )
    return ProjectArtifacts.from_dict(response)
