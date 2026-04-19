"""主流水线步骤实现。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent.artifact_plan import build_artifact_plan
from agent.generator import generate_project
from agent.models import (
    ArtifactFact,
    ArtifactPlan,
    EnvSpec,
    EvidenceItem,
    FinalVersionDecision,
    PipelineResult,
    ProjectArtifacts,
    ReproductionProfile,
    ResolvedTask,
    TaskInput,
    ValidationReport,
)
from agent.parser import parse_task
from agent.planner import build_env_spec
from agent.reproduction_profile import resolve_reproduction_profile
from agent.validator import validate_project
from tools import (
    collect_cve_evidence,
    create_run_directory,
    ensure_database_related_evidence,
    read_project_snapshot,
    write_pipeline_state,
    write_project,
)


@dataclass
class StepOutcome:
    """单个步骤在终端中展示的结果对象。"""

    thought: str
    action: str
    observation: str
    result: str
    duration_seconds: float


@dataclass
class RunState:
    """单轮流水线共享的中间状态。"""

    task: TaskInput | None = None
    resolved_task: ResolvedTask | None = None
    final_version_decision: FinalVersionDecision | None = None
    evidence: list[EvidenceItem] = field(default_factory=list)
    reproduction_profile: ReproductionProfile | None = None
    artifact_facts: list[ArtifactFact] = field(default_factory=list)
    artifact_plan: ArtifactPlan | None = None
    env_spec: EnvSpec | None = None
    artifacts: ProjectArtifacts | None = None
    validation: ValidationReport | None = None
    pipeline_result: PipelineResult | None = None
    run_dir: Path | None = None


class PipelineSteps:
    """承载主流水线各阶段的执行逻辑。"""

    def __init__(
        self,
        *,
        project_directory: Path,
        client,
        enable_validator: bool,
        log_agent_payload: Callable[[str, dict], None],
        build_final_version_decision: Callable[
            [TaskInput, ReproductionProfile, ArtifactPlan], FinalVersionDecision
        ],
        build_resolved_task: Callable[[TaskInput, FinalVersionDecision], ResolvedTask],
    ) -> None:
        """注入步骤执行所需的共享依赖。"""
        self.project_directory = project_directory
        self.client = client
        self.enable_validator = enable_validator
        self.log_agent_payload = log_agent_payload
        self.build_final_version_decision = build_final_version_decision
        self.build_resolved_task = build_resolved_task

    def handlers(self) -> list[Callable[[RunState, str, float], StepOutcome]]:
        """按主流程顺序返回所有步骤处理器。"""
        return [
            self.run_parse_step,
            self.run_evidence_step,
            self.run_reproduction_profile_step,
            self.run_artifact_plan_step,
            self.run_planner_step,
            self.run_generator_step,
            self.run_write_and_validate_step,
            self.run_state_write_step,
        ]

    def run_parse_step(
        self,
        state: RunState,
        user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """执行第 1 步：解析原始用户请求。"""
        state.task = parse_task(user_input, self.client)
        self.log_agent_payload("parser", state.task.to_dict())
        return StepOutcome(
            thought="先把原始需求整理成统一结构，避免后续阶段对同一输入产生不同理解。",
            action="parse_task(user_input, client)",
            observation=json.dumps(state.task.to_dict(), ensure_ascii=False, indent=2),
            result=(
                f"已识别 CVE 编号为 {state.task.cve_id or '未提供'}，"
                f"数据库类型为 {state.task.db_type}，请求版本为 {state.task.requested_version or state.task.version}。"
            ),
            duration_seconds=round(time.time() - step_start_time, 2),
        )

    def run_evidence_step(
        self,
        state: RunState,
        _user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """执行第 2 步：收集 CVE 相关外部证据。"""
        assert state.task is not None
        state.evidence = collect_cve_evidence(state.task)
        inferred_db_type = ensure_database_related_evidence(state.task, state.evidence)
        observation = [item.to_dict() for item in state.evidence]
        self.log_agent_payload("tools:evidence", {"evidence": observation})
        return StepOutcome(
            thought="如果任务带有 CVE，就先收集外部证据，为后续复现画像提供事实输入。",
            action="collect_cve_evidence(task)",
            observation=json.dumps(observation, ensure_ascii=False, indent=2),
            result=(
                f"已收集 {len(state.evidence)} 条外部证据，并识别为 {inferred_db_type or '未识别数据库类型'} 相关漏洞。"
                if state.task.cve_id
                else "当前任务未提供 CVE，跳过证据收集。"
            ),
            duration_seconds=round(time.time() - step_start_time, 2),
        )

    def run_reproduction_profile_step(
        self,
        state: RunState,
        _user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """执行第 3 步：生成证据驱动的复现约束画像。"""
        assert state.task is not None
        state.reproduction_profile = resolve_reproduction_profile(
            state.task, state.evidence, self.client
        )
        self.log_agent_payload(
            "reproduction_profile", state.reproduction_profile.to_dict()
        )
        return StepOutcome(
            thought="把任务输入和外部证据归纳成复现约束画像，让后续阶段围绕约束而不是预设分类工作。",
            action="resolve_reproduction_profile(task, evidence, client)",
            observation=json.dumps(
                state.reproduction_profile.to_dict(), ensure_ascii=False, indent=2
            ),
            result=(
                f"已生成复现画像，置信度为 {state.reproduction_profile.confidence}，"
                f"包含 {len(state.reproduction_profile.required_artifacts)} 条制品要求。"
            ),
            duration_seconds=round(time.time() - step_start_time, 2),
        )

    def run_artifact_plan_step(
        self,
        state: RunState,
        _user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """执行第 4 步：由 LLM 直接调用底层工具并生成结构化制品计划。"""
        assert state.task is not None
        assert state.reproduction_profile is not None
        state.artifact_plan, state.artifact_facts, react_trace = build_artifact_plan(
            state.task,
            state.reproduction_profile,
            self.client,
        )
        state.final_version_decision = self.build_final_version_decision(
            state.task,
            state.reproduction_profile,
            state.artifact_plan,
        )
        state.resolved_task = self.build_resolved_task(
            state.task,
            state.final_version_decision,
        )
        if (
            not state.task.db_type
            and state.artifact_plan.effective_db_type
            and state.resolved_task.db_type != state.artifact_plan.effective_db_type
        ):
            raise ValueError("最终任务决议未正确继承 artifact_plan 补齐后的数据库类型。")
        payload = {
            "react_trace": react_trace,
            "artifact_facts": [item.to_dict() for item in state.artifact_facts],
            "artifact_plan": state.artifact_plan.to_dict(),
            "final_version_decision": state.final_version_decision.to_dict(),
            "resolved_task": state.resolved_task.to_dict(),
        }
        self.log_agent_payload("artifact_plan", payload)
        return StepOutcome(
            thought="画像已经约束了语义，现在由制品计划 agent 直接调用底层工具查询镜像和源码事实，再统一生成制品计划，减少中间层损耗。",
            action="build_artifact_plan(task, reproduction_profile, client)",
            observation=json.dumps(payload, ensure_ascii=False, indent=2),
            result=(
                f"ReAct 共执行 {len(react_trace)} 轮。"
                f" 已确定主交付策略为 {state.artifact_plan.delivery_strategy}，"
                f"最终部署版本为 {state.resolved_task.final_version}。"
            ),
            duration_seconds=round(time.time() - step_start_time, 2),
        )

    def run_planner_step(
        self,
        state: RunState,
        _user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """执行第 5 步：生成环境规划。"""
        assert state.task is not None
        assert state.resolved_task is not None
        assert state.reproduction_profile is not None
        assert state.artifact_plan is not None
        state.env_spec = build_env_spec(
            state.task,
            state.resolved_task,
            state.reproduction_profile,
            state.artifact_plan,
            self.client,
        )
        state.env_spec.project_name = state.resolved_task.project_name
        state.env_spec.version = state.resolved_task.final_version
        self.log_agent_payload("planner", state.env_spec.to_dict())
        return StepOutcome(
            thought="复现约束和制品计划已经就位，接下来由 planner 设计满足这些约束的环境结构。",
            action="build_env_spec(task, resolved_task, reproduction_profile, artifact_plan, client)",
            observation=json.dumps(state.env_spec.to_dict(), ensure_ascii=False, indent=2),
            result=f"已完成环境规划，项目名为 {state.env_spec.project_name}。",
            duration_seconds=round(time.time() - step_start_time, 2),
        )

    def run_generator_step(
        self,
        state: RunState,
        _user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """执行第 6 步：生成完整项目文件内容。"""
        assert state.task is not None
        assert state.resolved_task is not None
        assert state.reproduction_profile is not None
        assert state.artifact_plan is not None
        assert state.env_spec is not None
        state.artifacts = generate_project(
            state.task,
            state.resolved_task,
            state.reproduction_profile,
            state.artifact_plan,
            state.env_spec,
            self.client,
        )
        self.log_agent_payload("generator", state.artifacts.to_dict())
        observation = {
            "cve_id": state.artifacts.cve_id,
            "project_name": state.artifacts.project_name,
            "generated_files": [file.path for file in state.artifacts.files],
        }
        return StepOutcome(
            thought="规划已经完成，现在由 generator 直接生成完整文件内容集合。",
            action="generate_project(task, resolved_task, reproduction_profile, artifact_plan, env_spec, client)",
            observation=json.dumps(observation, ensure_ascii=False, indent=2),
            result=f"已生成 {len(state.artifacts.files)} 个文件内容。",
            duration_seconds=round(time.time() - step_start_time, 2),
        )

    def run_write_and_validate_step(
        self,
        state: RunState,
        _user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """执行第 7 步：写盘并按需做运行性校验。"""
        assert state.task is not None
        assert state.resolved_task is not None
        assert state.reproduction_profile is not None
        assert state.artifact_plan is not None
        assert state.env_spec is not None
        assert state.artifacts is not None

        state.run_dir = create_run_directory(
            self.project_directory, state.resolved_task.project_name
        )
        written_files = write_project(state.run_dir, state.artifacts.files)

        if self.enable_validator:
            state.validation, state.artifacts, repaired = validate_project(
                task=state.task,
                resolved_task=state.resolved_task,
                reproduction_profile=state.reproduction_profile,
                artifact_plan=state.artifact_plan,
                env_spec=state.env_spec,
                artifacts=state.artifacts,
                run_dir=state.run_dir,
                client=self.client,
            )
            snapshot = read_project_snapshot(state.run_dir)
            observation = {
                "run_dir": str(state.run_dir),
                "written_files": written_files,
                "snapshot_files": [file.path for file in snapshot.files],
                "repaired_by_validator": repaired,
                "validation": state.validation.to_dict(),
            }
            self.log_agent_payload("validator", observation)
            if not state.validation.passed:
                raise ValueError("项目校验失败: " + "; ".join(state.validation.findings))
            result = "运行性校验通过。"
            thought = "先把文件写到真实目录，再由 validator 基于磁盘快照做运行性校验和按需修复。"
            action = (
                "create_run_directory(...) -> write_project(...) -> "
                "validate_project(task, resolved_task, reproduction_profile, artifact_plan, env_spec, artifacts, run_dir, client)"
            )
        else:
            state.validation = ValidationReport(
                passed=True,
                findings=[],
                warnings=["用户通过命令行参数跳过 validator 阶段，项目未经过自动校验。"],
                repair_instructions=[],
            )
            observation = {
                "run_dir": str(state.run_dir),
                "written_files": written_files,
                "validator_enabled": False,
                "validation": state.validation.to_dict(),
            }
            self.log_agent_payload("tools", observation)
            result = "项目已写入，validator 运行性校验已按用户参数跳过。"
            thought = "本轮只需要快速生成项目并写入磁盘，因此跳过 validator 运行性校验。"
            action = "create_run_directory(...) -> write_project(...)"

        return StepOutcome(
            thought=thought,
            action=action,
            observation=json.dumps(observation, ensure_ascii=False, indent=2),
            result=result,
            duration_seconds=round(time.time() - step_start_time, 2),
        )

    def run_state_write_step(
        self,
        state: RunState,
        _user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """执行第 8 步：写入状态文件并汇总最终结果。"""
        assert state.task is not None
        assert state.resolved_task is not None
        assert state.final_version_decision is not None
        assert state.reproduction_profile is not None
        assert state.artifact_plan is not None
        assert state.env_spec is not None
        assert state.artifacts is not None
        assert state.validation is not None
        assert state.run_dir is not None

        state_files = write_pipeline_state(
            run_dir=state.run_dir,
            task=state.task,
            resolved_task=state.resolved_task,
            final_version_decision=state.final_version_decision,
            evidence=state.evidence,
            reproduction_profile=state.reproduction_profile,
            artifact_facts=state.artifact_facts,
            artifact_plan=state.artifact_plan,
            env_spec=state.env_spec,
            artifacts=state.artifacts,
            validation=state.validation,
        )
        state.pipeline_result = PipelineResult(
            run_dir=state.run_dir,
            task=state.task,
            resolved_task=state.resolved_task,
            final_version_decision=state.final_version_decision,
            evidence=state.evidence,
            reproduction_profile=state.reproduction_profile,
            artifact_facts=state.artifact_facts,
            artifact_plan=state.artifact_plan,
            env_spec=state.env_spec,
            artifacts=state.artifacts,
            validation=state.validation,
        )
        self.log_agent_payload("tools", state.pipeline_result.to_dict())
        return StepOutcome(
            thought="项目文件已经稳定后，再把结构化状态写入 state 目录，方便后续回溯。",
            action="write_pipeline_state(run_dir, task, resolved_task, final_version_decision, evidence, reproduction_profile, artifact_facts, artifact_plan, env_spec, artifacts, validation)",
            observation=json.dumps(
                {
                    "run_dir": str(state.run_dir),
                    "state_files": state_files,
                },
                ensure_ascii=False,
                indent=2,
            ),
            result=f"项目已写入 {state.run_dir}，状态文件已同步落盘。",
            duration_seconds=round(time.time() - step_start_time, 2),
        )
