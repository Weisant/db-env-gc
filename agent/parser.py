"""LLM 驱动的任务解析器。

这个模块只做一件事：
把用户输入整理成后续 agent 都能稳定消费的 `TaskInput`。
它不接触文件系统，也不生成任何 Docker 项目内容。
"""

from __future__ import annotations

import json

from agent.llm import JsonChatClient
from agent.models import TaskInput
from agent.prompt_loader import load_prompt


def parse_task(raw_request: str, client: JsonChatClient) -> TaskInput:
    """使用 LLM 将用户输入标准化为 TaskInput。"""
    raw_request = raw_request.strip()
    if not raw_request:
        raise ValueError("任务内容不能为空。")

    # parser prompt 只负责“理解需求并结构化”，不参与后续项目生成。
    system_prompt = load_prompt("parser.md")
    user_prompt = (
        "请将下面的用户请求整理为标准化任务 JSON。\n\n"
        f"{json.dumps({'raw_request': raw_request}, ensure_ascii=False, indent=2)}"
    )
    response = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0,
        model=client.settings.parser_model,
    )
    # 无论模型是否回显 `raw_request`，这里都以当前真实输入为准，避免上下文漂移。
    task_data = dict(response)
    task_data["raw_request"] = raw_request
    return TaskInput.from_dict(task_data)
