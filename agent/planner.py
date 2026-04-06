"""LLM 驱动的环境规划器。

planner 只负责产出“这个项目应该包含哪些内容、需要满足哪些约束”的结构化理解，
不会直接写文件，也不会执行任何文件系统操作。
"""

from __future__ import annotations

import json

from agent.llm import JsonChatClient
from agent.models import EnvSpec, TaskInput
from agent.prompt_loader import load_prompt


def build_env_spec(task: TaskInput, client: JsonChatClient) -> EnvSpec:
    """使用 LLM 生成环境规划规格。"""
    # planner 的输入固定来自 parser 输出的 TaskInput，这样可以减少自由文本带来的歧义。
    system_prompt = load_prompt("planner.md")
    user_prompt = (
        "请根据下面的标准化任务，生成环境规划 JSON。\n\n"
        f"{json.dumps(task.to_dict(), ensure_ascii=False, indent=2)}"
    )
    response = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
    )
    return EnvSpec.from_dict(response)
