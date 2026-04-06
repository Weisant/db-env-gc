"""LLM 驱动的 Docker 项目生成器。

generator 的职责非常单一：
只生成“文件内容本身”，不负责写盘。
真正的写文件动作会交给 `agent/tools` 目录下的工具层完成。
"""

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
    # generator prompt 会拿到 parser 和 planner 的结构化结果，
    # 然后一次性生成完整文件内容集合，供 tools 写入磁盘。
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
