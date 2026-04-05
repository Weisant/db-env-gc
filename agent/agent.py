"""Plan-and-execute 风格的数据库环境生成 agent。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import load_settings
from agent.generator import generate_project
from agent.llm import JsonChatClient
from agent.models import EnvSpec, PipelineResult, ProjectArtifacts, TaskInput, ValidationReport
from agent.parser import parse_task
from agent.persist import persist_result
from agent.planner import build_env_spec
from agent.validator import validate_artifacts


@dataclass
class StepOutcome:
    """单步执行结果。"""

    thought: str
    action: str
    observation: str
    result: str


class DBEnvGenerationAgent:
    """用于生成数据库 Docker 环境项目的受控 Agent。"""

    def __init__(self, project_directory: Path, log_file_path: Path) -> None:
        self.project_directory = project_directory
        self.log_file_path = log_file_path
        self.client = JsonChatClient(load_settings())

    def run(self, user_input: str) -> str:
        """执行完整流水线,固定的5个任务列表。"""
        plan = self.create_plan()
        print("\n" + "=" * 72)
        print("📝 初始计划")
        print("=" * 72)
        for index, step in enumerate(plan, start=1):
            print(f"{index}. {step}")

        completed_steps: list[tuple[str, str]] = []
        task: TaskInput | None = None
        env_spec: EnvSpec | None = None
        artifacts: ProjectArtifacts | None = None
        validation: ValidationReport | None = None
        pipeline_result: PipelineResult | None = None

        for index, step in enumerate(plan, start=1):
            print("\n" + "=" * 72)
            print(f"🚀 任务 {index} 开始")
            print(f"当前任务：{step}")
            print("=" * 72)

            # Step 1：parser agent 解析用户输入并标准化需求
            if index == 1:
                task = parse_task(user_input)
                outcome = StepOutcome(
                    thought="需要先把用户输入规范化，才能稳定地规划后续环境文件。",
                    action="parse_task(user_input)",
                    observation=json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
                    result=f"已识别数据库类型为 {task.db_type}，版本为 {task.version}。",
                )
                self.log_agent_payload("parser", task.to_dict())
            # Step 2：planner agent 生成环境规划，明确输出结构
            elif index == 2:
                assert task is not None
                env_spec = build_env_spec(task, self.client)
                outcome = StepOutcome(
                    thought="任务信息已经明确，现在由 LLM 生成环境规划，而不是按数据库类型套硬编码模板。",
                    action="build_env_spec(task, client)",
                    observation=json.dumps(env_spec.to_dict(), ensure_ascii=False, indent=2),
                    result=(
                        f"已完成环境规划，项目名为 {env_spec.project_name}。"
                    ),
                )
                self.log_agent_payload("planner", env_spec.to_dict())
            # Step 3：generator agent 直接生成完整的 Docker 项目文件集合
            elif index == 3:
                assert task is not None
                assert env_spec is not None
                artifacts = generate_project(task, env_spec, self.client)
                observation = {
                    "project_name": artifacts.project_name,
                    "generated_files": [file.path for file in artifacts.files],
                }
                outcome = StepOutcome(
                    thought="规划已完成，现在由 LLM 直接生成完整 Docker 项目文件。",
                    action="generate_project(task, env_spec, client)",
                    observation=json.dumps(observation, ensure_ascii=False, indent=2),
                    result=f"已生成 {len(artifacts.files)} 个项目文件。",
                )
                self.log_agent_payload("generator", artifacts.to_dict())
            # Step 4：validator agent 校验项目完整性与配置一致性
            elif index == 4:
                assert env_spec is not None
                assert artifacts is not None
                validation = validate_artifacts(env_spec.db_type, artifacts)
                outcome = StepOutcome(
                    thought="写盘之前需要先检查文件完整性，避免交付不完整项目。",
                    action="validate_artifacts(env_spec.db_type, artifacts)",
                    observation=json.dumps(validation.to_dict(), ensure_ascii=False, indent=2),
                    result="校验通过。" if validation.passed else "校验失败。",
                )
                self.log_agent_payload("validator", validation.to_dict())
                if not validation.passed:
                    raise ValueError("项目校验失败: " + "; ".join(validation.findings))
            # Step 5：writer agent 将项目写入输出目录并整理交付信息
            else:
                assert task is not None
                assert env_spec is not None
                assert artifacts is not None
                assert validation is not None
                pipeline_result = persist_result(
                    output_root=self.project_directory,
                    task=task,
                    env_spec=env_spec,
                    artifacts=artifacts,
                    validation=validation,
                )
                observation = {
                    "run_dir": str(pipeline_result.run_dir),
                    "state_files": [
                        "state/task.json",
                        "state/env_spec.json",
                        "state/artifacts.json",
                        "state/validation.json",
                    ],
                }
                outcome = StepOutcome(
                    thought="校验通过后可以安全落盘，并整理最后的交付路径。",
                    action="persist_result(output_root, task, env_spec, artifacts, validation)",
                    observation=json.dumps(observation, ensure_ascii=False, indent=2),
                    result=f"项目已写入 {pipeline_result.run_dir}。",
                )
                self.log_agent_payload("writer", pipeline_result.to_dict())

            self._print_outcome(index, outcome)
            completed_steps.append((step, outcome.result))
            self._print_remaining_plan(plan[index:])

        assert pipeline_result is not None
        return self.create_final_answer(pipeline_result)

    def create_plan(self) -> list[str]:
        """创建固定的受控计划。"""
        return [
            "解析用户输入并标准化数据库环境需求",
            "生成环境规划，明确要输出的 Docker 项目结构",
            "调用 LLM 生成完整的 Docker 项目文件集合",
            "校验项目完整性与配置一致性",
            "将项目写入输出目录并整理交付信息",
        ]

    def create_final_answer(self, result: PipelineResult) -> str:
        """构造最终回复。"""
        generated_files = ", ".join(file.path for file in result.artifacts.files)
        warnings = (
            f" 警告：{'；'.join(result.validation.warnings)}"
            if result.validation.warnings
            else ""
        )
        return (
            f"已生成 {result.task.db_type} {result.task.version} 的 Docker 环境项目，"
            f"输出目录为 {result.run_dir}。主要文件包括 {generated_files}。"
            f"{warnings}"
        )

    def _print_outcome(self, operation_index: int, outcome: StepOutcome) -> None:
        print(f"\n[{operation_index}] 💭 Thought:")
        print(outcome.thought)
        print(f"\n[{operation_index}] 🔧 Action: {outcome.action}")
        print(f"\n[{operation_index}] 🔍 Observation:")
        print(outcome.observation)
        print(f"\n[{operation_index}] ✅ Step Result:")
        print(outcome.result)
        print("-" * 72)
        print("✅ 当前任务执行完成")
        print("-" * 72)

    def _print_remaining_plan(self, remaining_steps: list[str]) -> None:
        if not remaining_steps:
            return
        print("\n" + "-" * 72)
        print("🔄 更新后的剩余计划")
        print("-" * 72)
        for index, step in enumerate(remaining_steps, start=1):
            print(f"{index}. {step}")

    def log_agent_payload(self, agent_name: str, payload: dict[str, Any]) -> None:
        """将结构化阶段结果写入日志。"""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agent_name": agent_name,
            "payload": payload,
        }
        with self.log_file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, indent=2))
            file.write("\n\n")
