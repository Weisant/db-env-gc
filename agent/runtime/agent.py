"""Plan-and-Execute 风格的主调度器。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import load_settings
from agent.llm import JsonChatClient
from agent.models import (
    ArtifactPlan,
    FinalVersionDecision,
    PipelineResult,
    ReproductionProfile,
    ResolvedTask,
    TaskInput,
)
from agent.runtime.pipeline_steps import PipelineSteps, RunState, StepOutcome


class DBEnvGenerationAgent:
    """数据库环境项目生成主调度器。"""

    def __init__(
        self,
        project_directory: Path,
        log_file_path: Path,
        enable_validator: bool = True,
    ) -> None:
        """初始化主调度器和共享 LLM 客户端。"""
        self.project_directory = project_directory
        self.log_file_path = log_file_path
        self.enable_validator = enable_validator
        self.client = JsonChatClient(load_settings())

    def run(self, user_input: str) -> str:
        """执行完整流水线。"""
        plan = self.create_plan()
        print("\n" + "=" * 72)
        print("📝 初始计划")
        print("=" * 72)
        for index, step in enumerate(plan, start=1):
            print(f"{index}. {step}")

        runner = PipelineSteps(
            project_directory=self.project_directory,
            client=self.client,
            enable_validator=self.enable_validator,
            log_agent_payload=self.log_agent_payload,
            build_final_version_decision=self._build_final_version_decision,
            build_resolved_task=self._build_resolved_task,
        )
        run_state = RunState()
        step_handlers = runner.handlers()

        for index, step in enumerate(plan, start=1):
            print("\n" + "=" * 72)
            print(f"🚀 任务 {index} 开始")
            print(f"当前阶段执行方为：{self.get_step_executor_label(index)}")
            print(f"当前任务：{step}")
            print("=" * 72)
            step_start_time = time.time()
            outcome = step_handlers[index - 1](run_state, user_input, step_start_time)
            self._print_outcome(index, outcome)
            self._print_remaining_plan(plan[index:])

        assert run_state.pipeline_result is not None
        return self.create_final_answer(run_state.pipeline_result)

    def create_plan(self) -> list[str]:
        """定义固定的执行计划。"""
        step_seven = (
            "使用 tools 写入项目，并由 validator 做运行性校验和按需修复"
            if self.enable_validator
            else "使用 tools 写入项目，并按用户参数跳过 validator 运行性校验"
        )
        return [
            "解析用户输入并标准化数据库环境需求",
            "围绕 CVE 与数据库上下文收集外部证据",
            "生成证据驱动的复现约束画像",
            "由 artifact-plan agent 直接查询制品事实并生成结构化制品计划",
            "生成环境规划，明确要输出的 Docker 项目结构",
            "调用 LLM 生成完整的 Docker 项目文件内容集合",
            step_seven,
            "使用 tools 写入状态文件并整理最终交付信息",
        ]

    def create_final_answer(self, result: PipelineResult) -> str:
        """构造最终自然语言回复。"""
        generated_files = ", ".join(file.path for file in result.artifacts.files)
        resolution_notes = [
            item
            for item in [
                result.artifact_plan.selected_image,
                result.artifact_plan.selected_download_url,
            ]
            if item
        ]
        warnings = (
            f" 警告：{'；'.join(result.validation.warnings)}"
            if result.validation.warnings
            else ""
        )
        profile_note = (
            f"复现画像置信度为 {result.reproduction_profile.confidence}。"
            if result.reproduction_profile.confidence
            else ""
        )
        version_adjustment_note = (
            f" 由于原始请求版本 {result.resolved_task.requested_version} 与复现约束冲突，环境实际部署版本已自动调整为 {result.resolved_task.final_version}。"
            if result.resolved_task.requested_version
            and result.resolved_task.final_version
            and result.resolved_task.final_version != result.resolved_task.requested_version
            else ""
        )
        artifact_note = (
            f" 关键制品包括 {'，'.join(resolution_notes[:3])}。"
            if resolution_notes
            else ""
        )
        return (
            f"已生成 "
            f"{result.task.cve_id + ' 对应的' if result.task.cve_id else ''}"
            f"{result.resolved_task.db_type} {result.resolved_task.final_version or result.env_spec.version or result.task.version} Docker 环境项目，"
            f"输出目录为 {result.run_dir}。"
            f"{profile_note}{version_adjustment_note}{artifact_note}"
            f"主要文件包括 {generated_files}。"
            f"{warnings}"
        )

    def get_step_executor_label(self, step_index: int) -> str:
        """根据步骤序号返回当前阶段的执行方标签。"""
        executor_labels = {
            1: "parser agent",
            2: "evidence tool",
            3: "reproduction-profile agent",
            4: "artifact-plan agent + artifact tools",
            5: "planner agent",
            6: "generator agent",
            7: "runtime-validator agent + file tools" if self.enable_validator else "file tools",
            8: "state tool",
        }
        return executor_labels.get(step_index, "unknown")

    def _build_final_version_decision(
        self,
        task: TaskInput,
        reproduction_profile: ReproductionProfile,
        artifact_plan: ArtifactPlan,
    ) -> FinalVersionDecision:
        """把制品计划收敛成统一最终版本决议。"""
        requested_version = task.requested_version or task.version
        final_version = artifact_plan.selected_version or requested_version
        version_source = artifact_plan.version_source or "requested"
        version_reason = artifact_plan.reason or "制品计划未给出额外原因，沿用当前决议。"
        delivery_strategy = artifact_plan.delivery_strategy or "source_build"
        delivery_reason = artifact_plan.reason or "制品计划未给出交付原因。"
        return FinalVersionDecision(
            project_name=artifact_plan.project_name,
            effective_db_type=artifact_plan.effective_db_type or task.db_type,
            requested_version=requested_version,
            final_version=final_version,
            version_source=version_source,
            version_reason=version_reason,
            delivery_strategy=delivery_strategy,
            delivery_reason=delivery_reason,
            blocked_versions=reproduction_profile.version_policy.excluded_versions,
            selection_confidence=artifact_plan.confidence or reproduction_profile.confidence,
            primary_requirement_name=artifact_plan.primary_artifact_kind or "primary-runtime",
        )

    def _print_outcome(self, operation_index: int, outcome: StepOutcome) -> None:
        """统一打印单步结果。"""
        print("\n 💭 Thought:")
        print(outcome.thought)
        print(f"\n 🔧 Action: {outcome.action}")
        print("\n 🔍 Observation:")
        print(outcome.observation)
        print("\n ✅ Step Result:")
        print(outcome.result)
        print("\n ⏱️ Step Duration:")
        print(f"{outcome.duration_seconds} 秒")
        print("-" * 72)
        print("✅ 当前任务执行完成")
        print("-" * 72)

    def _print_remaining_plan(self, remaining_steps: list[str]) -> None:
        """打印剩余计划，帮助用户理解流水线接下来会做什么。"""
        if not remaining_steps:
            return
        print("\n" + "-" * 72)
        print("🔄 更新后的剩余计划")
        print("-" * 72)
        for index, step in enumerate(remaining_steps, start=1):
            print(f"{index}. {step}")

    def log_agent_payload(self, agent_name: str, payload: dict[str, Any]) -> None:
        """把各阶段结构化输出写入日志文件。"""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agent_name": agent_name,
            "payload": payload,
        }
        with self.log_file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, indent=2))
            file.write("\n\n")

    def _build_resolved_task(
        self,
        task: TaskInput,
        final_version_decision: FinalVersionDecision,
    ) -> ResolvedTask:
        """把工具层的版本决议包装成统一最终任务对象。"""
        return ResolvedTask(
            cve_id=task.cve_id,
            db_type=final_version_decision.effective_db_type or task.db_type,
            requested_version=final_version_decision.requested_version,
            final_version=final_version_decision.final_version,
            project_name=final_version_decision.project_name,
            version_source=final_version_decision.version_source,
            version_reason=final_version_decision.version_reason,
            delivery_strategy=final_version_decision.delivery_strategy,
            delivery_reason=final_version_decision.delivery_reason,
            blocked_versions=final_version_decision.blocked_versions,
            selection_confidence=final_version_decision.selection_confidence,
        )
