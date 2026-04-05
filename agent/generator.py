"""LLM 驱动的 Docker 项目生成器。"""

from __future__ import annotations

import json

from agent.llm import JsonChatClient
from agent.models import ProjectArtifacts, TaskInput, EnvSpec
from agent.prompt_loader import load_prompt


def generate_project(
    task: TaskInput,
    env_spec: EnvSpec,
    client: JsonChatClient,
) -> ProjectArtifacts:
    """让 LLM 直接返回完整项目文件集合。"""
    system_prompt = load_prompt("writer.md")
    user_prompt = (
        "请根据下面的信息生成完整 Docker 项目文件集合 JSON。\n\n"
        "标准化任务：\n"
        f"{json.dumps(task.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "环境规划：\n"
        f"{json.dumps(env_spec.to_dict(), ensure_ascii=False, indent=2)}"
    )
    response = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.2,
    )
    return ProjectArtifacts.from_dict(response)
