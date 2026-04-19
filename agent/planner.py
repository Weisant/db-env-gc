"""LLM 驱动的环境规划器。

planner 只负责产出“这个项目应该包含哪些内容、需要满足哪些约束”的结构化理解，
不会直接写文件，也不会执行任何文件系统操作。
"""

from __future__ import annotations

import json

from agent.llm import JsonChatClient
from agent.models import (
    ArtifactPlan,
    EnvSpec,
    ReproductionProfile,
    ResolvedTask,
    TaskInput,
)
from agent.runtime.payload_builders import (
    build_artifact_plan_summary,
    build_profile_summary,
    build_resolved_task_summary,
)
from agent.prompt_loader import load_prompt


def build_env_spec(
    task: TaskInput,
    resolved_task: ResolvedTask,
    reproduction_profile: ReproductionProfile,
    artifact_plan: ArtifactPlan,
    client: JsonChatClient,
) -> EnvSpec:
    """使用 LLM 生成环境规划规格。"""
    # planner 的输入固定来自 parser 输出的 TaskInput，以及证据驱动的复现画像，
    # 这样可以减少自由文本带来的歧义，并让约束显式化。
    system_prompt = load_prompt("planner.md")
    user_prompt = (
        "请根据下面的标准化任务、复现画像和制品计划，生成环境规划 JSON。\n\n"
        "标准化任务：\n"
        f"{json.dumps(build_resolved_task_summary(task, resolved_task), ensure_ascii=False, indent=2)}\n\n"
        "复现画像：\n"
        f"{json.dumps(build_profile_summary(reproduction_profile, artifact_limit=5, capability_limit=5, note_limit=3), ensure_ascii=False, indent=2)}\n\n"
        "制品计划：\n"
        f"{json.dumps(build_artifact_plan_summary(artifact_plan), ensure_ascii=False, indent=2)}"
    )
    response = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        model=client.settings.planner_model,
    )
    return EnvSpec.from_dict(response)
