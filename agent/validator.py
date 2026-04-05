"""LLM 驱动的项目校验器。"""

from __future__ import annotations

import json

from agent.llm import JsonChatClient
from agent.models import EnvSpec, ProjectArtifacts, TaskInput, ValidationReport
from agent.prompt_loader import load_prompt


def validate_artifacts(
    task: TaskInput,
    env_spec: EnvSpec,
    artifacts: ProjectArtifacts,
    client: JsonChatClient,
) -> ValidationReport:
    """使用 LLM 对生成项目做结构与一致性校验。"""
    system_prompt = load_prompt("validator.md")
    user_prompt = (
        "请检查下面的数据库 Docker 项目是否完整、自洽、可交付。\n\n"
        "标准化任务：\n"
        f"{json.dumps(task.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "环境规划：\n"
        f"{json.dumps(env_spec.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "当前项目文件集合：\n"
        f"{json.dumps(artifacts.to_dict(), ensure_ascii=False, indent=2)}"
    )
    response = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0,
    )
    return ValidationReport.from_dict(response)
