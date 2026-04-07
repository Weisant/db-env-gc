"""Plan-and-Execute 风格的主调度器。

这个模块是整个项目的编排中心：
1. 负责按固定顺序调用 parser / planner / generator / validator
2. 负责在合适的时机调用 tools 写盘、读快照、写状态
3. 负责把每一步的中间结果打印成终端日志

注意：
- generator 只负责生成内容，不写文件
- validator 会在必要时自动修复项目
- tools 负责确定性辅助步骤和文件系统操作，不参与内容生成
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import load_settings
from agent.generator import generate_project
from agent.llm import JsonChatClient
from agent.models import (
    EnvSpec,
    ImageResolution,
    PipelineResult,
    ProjectArtifacts,
    TaskInput,
    ValidationReport,
    VersionResolution,
)
from agent.parser import parse_task
from agent.planner import build_env_spec
from agent.validator import validate_project
from tools import (
    create_run_directory,
    read_project_snapshot,
    resolve_image_source,
    resolve_version_source,
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


class DBEnvGenerationAgent:
    """数据库环境项目生成主调度器。"""

    def __init__(
        self,
        project_directory: Path,
        log_file_path: Path,
        enable_validator: bool = True,
    ) -> None:
        self.project_directory = project_directory
        self.log_file_path = log_file_path
        # 这里允许调用方按需关闭 validator，
        # 适合只想快速生成项目、不关心自动校验与自动修复的场景。
        self.enable_validator = enable_validator
        self.client = JsonChatClient(load_settings())

    def run(self, user_input: str) -> str:
        """执行完整流水线。

        当前版本的主链路为：
        parser -> version-source-tools -> image-resolution-tools -> planner -> generator -> tools写盘 -> validator(可选，含自动修复) -> tools写状态
        """
        plan = self.create_plan()
        print("\n" + "=" * 72)
        print("📝 初始计划")
        print("=" * 72)
        for index, step in enumerate(plan, start=1):
            print(f"{index}. {step}")

        task: TaskInput | None = None
        version_resolution: VersionResolution | None = None
        image_resolution: ImageResolution | None = None
        env_spec: EnvSpec | None = None
        artifacts: ProjectArtifacts | None = None
        validation: ValidationReport | None = None
        pipeline_result: PipelineResult | None = None
        run_dir: Path | None = None

        for index, step in enumerate(plan, start=1):
            print("\n" + "=" * 72)
            print(f"🚀 任务 {index} 开始")
            print(f"当前阶段执行方：{self.get_step_executor_label(index)}")
            print(f"当前任务：{step}")
            print("=" * 72)
            # 每个阶段单独计时，方便定位真正慢的是哪个 agent。
            step_start_time = time.time()

            if index == 1:
                task = parse_task(user_input, self.client)
                outcome = StepOutcome(
                    thought="先把原始需求整理成统一结构，避免后续 agent 对同一输入产生不同理解。",
                    action="parse_task(user_input, client)",
                    observation=json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
                    result=(
                        f"已识别 CVE 编号为 {task.cve_id or '未提供'}，"
                        f"数据库类型为 {task.db_type}，版本为 {task.version}。"
                    ),
                    duration_seconds=round(time.time() - step_start_time, 2),
                )
                self.log_agent_payload("parser", task.to_dict())
            elif index == 2:
                assert task is not None
                version_resolution = resolve_version_source(task)
                outcome = StepOutcome(
                    thought="先用项目内置的官方源码源规则确认数据库版本是否真实存在，避免为不存在的版本继续生成环境。",
                    action="resolve_version_source(task)",
                    observation=json.dumps(version_resolution.to_dict(), ensure_ascii=False, indent=2),
                    result=(
                        f"版本存在性状态为 {version_resolution.availability}。"
                        f"{' 已确认版本存在。' if version_resolution.version_exists else ' 当前版本未通过真实性校验。'}"
                    ),
                    duration_seconds=round(time.time() - step_start_time, 2),
                )
                self.log_agent_payload("tools:version_resolution", version_resolution.to_dict())
            elif index == 3:
                assert task is not None
                assert version_resolution is not None
                image_resolution = resolve_image_source(task)
                outcome = StepOutcome(
                    thought="先确认 Docker Hub 上是否存在目标官方镜像 tag，再决定后续应走 image 还是 Dockerfile 分支。",
                    action="resolve_image_source(task)",
                    observation=json.dumps(image_resolution.to_dict(), ensure_ascii=False, indent=2),
                    result=(
                        f"镜像策略已确定为 {image_resolution.strategy}，"
                        f"可用性状态为 {image_resolution.availability}。"
                    ),
                    duration_seconds=round(time.time() - step_start_time, 2),
                )
                self.log_agent_payload("tools:image_resolution", image_resolution.to_dict())
            elif index == 4:
                assert task is not None
                assert version_resolution is not None
                assert image_resolution is not None
                env_spec = build_env_spec(task, image_resolution, self.client)
                outcome = StepOutcome(
                    thought="镜像来源已经确定，接下来由 planner 明确项目结构和约束。",
                    action="build_env_spec(task, image_resolution, client)",
                    observation=json.dumps(env_spec.to_dict(), ensure_ascii=False, indent=2),
                    result=f"已完成环境规划，项目名为 {env_spec.project_name}。",
                    duration_seconds=round(time.time() - step_start_time, 2),
                )
                self.log_agent_payload("planner", env_spec.to_dict())
            elif index == 5:
                assert task is not None
                assert version_resolution is not None
                assert image_resolution is not None
                assert env_spec is not None
                artifacts = generate_project(task, image_resolution, env_spec, self.client)
                outcome = StepOutcome(
                    thought="规划已经完成，现在由 generator 直接生成完整文件内容集合。",
                    action="generate_project(task, image_resolution, env_spec, client)",
                    observation=json.dumps(
                        {
                            "cve_id": artifacts.cve_id,
                            "project_name": artifacts.project_name,
                            "generated_files": [file.path for file in artifacts.files],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    result=f"已生成 {len(artifacts.files)} 个文件内容。",
                    duration_seconds=round(time.time() - step_start_time, 2),
                )
                self.log_agent_payload("generator", artifacts.to_dict())
            elif index == 6:
                assert task is not None
                assert version_resolution is not None
                assert image_resolution is not None
                assert env_spec is not None
                assert artifacts is not None

                # 这里是 tools 层第一次介入：先把 generator 生成的内容真正写到磁盘。
                run_dir = create_run_directory(self.project_directory, env_spec.project_name)
                written_files = write_project(run_dir, artifacts.files)

                if self.enable_validator:
                    # validator 读取真实磁盘快照进行检查，并在必要时自动修复。
                    validation, artifacts, repaired = validate_project(
                        task=task,
                        image_resolution=image_resolution,
                        env_spec=env_spec,
                        artifacts=artifacts,
                        run_dir=run_dir,
                        client=self.client,
                    )
                    snapshot = read_project_snapshot(run_dir)

                    observation = {
                        "run_dir": str(run_dir),
                        "written_files": written_files,
                        "snapshot_files": [file.path for file in snapshot.files],
                        "repaired_by_validator": repaired,
                        "validation": validation.to_dict(),
                    }
                    outcome = StepOutcome(
                        thought="先把文件写到真实目录，再由 validator 基于磁盘快照做校验和按需修复。",
                        action=(
                            "create_run_directory(...) -> write_project(...) -> "
                            "validate_project(task, image_resolution, env_spec, artifacts, run_dir, client)"
                        ),
                        observation=json.dumps(observation, ensure_ascii=False, indent=2),
                        result="校验通过。" if validation.passed else "校验失败。",
                        duration_seconds=round(time.time() - step_start_time, 2),
                    )
                    self.log_agent_payload("validator", observation)
                    if not validation.passed:
                        raise ValueError("项目校验失败: " + "; ".join(validation.findings))
                else:
                    # 当用户通过 CLI 参数关闭 validator 时，
                    # 这里仍然构造一份结构化校验结果，方便后续状态文件和最终摘要保持统一。
                    validation = ValidationReport(
                        passed=True,
                        findings=[],
                        warnings=["用户通过命令行参数跳过 validator 阶段，项目未经过自动校验。"],
                        repair_instructions=[],
                    )
                    observation = {
                        "run_dir": str(run_dir),
                        "written_files": written_files,
                        "validator_enabled": False,
                        "validation": validation.to_dict(),
                    }
                    outcome = StepOutcome(
                        thought="本轮只需要快速生成项目并写入磁盘，因此跳过 validator 阶段。",
                        action="create_run_directory(...) -> write_project(...)",
                        observation=json.dumps(observation, ensure_ascii=False, indent=2),
                        result="项目已写入，validator 已按用户参数跳过。",
                        duration_seconds=round(time.time() - step_start_time, 2),
                    )
                    self.log_agent_payload("tools", observation)
            else:
                assert task is not None
                assert version_resolution is not None
                assert image_resolution is not None
                assert env_spec is not None
                assert artifacts is not None
                assert validation is not None
                assert run_dir is not None

                state_files = write_pipeline_state(
                    run_dir=run_dir,
                    task=task,
                    version_resolution=version_resolution,
                    image_resolution=image_resolution,
                    env_spec=env_spec,
                    artifacts=artifacts,
                    validation=validation,
                )
                pipeline_result = PipelineResult(
                    run_dir=run_dir,
                    task=task,
                    version_resolution=version_resolution,
                    image_resolution=image_resolution,
                    env_spec=env_spec,
                    artifacts=artifacts,
                    validation=validation,
                )
                outcome = StepOutcome(
                    thought="项目文件已经稳定后，再把结构化状态写入 state 目录，方便后续回溯。",
                    action="write_pipeline_state(run_dir, task, image_resolution, env_spec, artifacts, validation)",
                    observation=json.dumps(
                        {
                            "run_dir": str(run_dir),
                            "state_files": state_files,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    result=f"项目已写入 {run_dir}，状态文件已同步落盘。",
                    duration_seconds=round(time.time() - step_start_time, 2),
                )
                self.log_agent_payload("tools", pipeline_result.to_dict())

            self._print_outcome(index, outcome)
            if (
                index == 2
                and version_resolution is not None
                and version_resolution.availability != "version_found"
            ):
                raise ValueError(
                    "未在项目内置的官方源码源中确认该数据库版本存在: "
                    + "；".join(version_resolution.notes)
                )
            self._print_remaining_plan(plan[index:])

        assert pipeline_result is not None
        return self.create_final_answer(pipeline_result)

    def create_plan(self) -> list[str]:
        """定义固定的执行计划。"""
        step_four = (
            "使用 tools 写入项目，并由 validator 校验和按需修复"
            if self.enable_validator
            else "使用 tools 写入项目，并按用户参数跳过 validator 校验"
        )
        return [
            "解析用户输入并标准化数据库环境需求",
            "查询官方源码源并确认数据库版本是否真实存在",
            "查询 Docker Hub 官方镜像可用性并确定镜像策略",
            "生成环境规划，明确要输出的 Docker 项目结构",
            "调用 LLM 生成完整的 Docker 项目文件内容集合",
            step_four,
            "使用 tools 写入状态文件并整理最终交付信息",
        ]

    def create_final_answer(self, result: PipelineResult) -> str:
        """构造最终自然语言回复。"""
        generated_files = ", ".join(file.path for file in result.artifacts.files)
        warnings = (
            f" 警告：{'；'.join(result.validation.warnings)}"
            if result.validation.warnings
            else ""
        )
        return (
            f"已生成 "
            f"{result.task.cve_id + ' 对应的' if result.task.cve_id else ''}"
            f"{result.task.db_type} {result.task.version} Docker 环境项目，"
            f"输出目录为 {result.run_dir}。"
            f"{' 使用官方镜像 ' + result.image_resolution.image_ref + '。' if result.image_resolution.strategy == 'official_image' else ' 未找到可直接使用的官方精确 tag，已改用 Dockerfile 自定义镜像。'}"
            f"主要文件包括 {generated_files}。"
            f"{warnings}"
        )

    def get_step_executor_label(self, step_index: int) -> str:
        """根据步骤序号返回当前阶段的执行方标签。

        这里刻意不用“当前 Agent”这种说法，
        因为有些阶段是 `validator + tools` 这种组合执行，而不是单一 agent。
        """
        executor_labels = {
            1: "parser",
            2: "tools",
            3: "tools",
            4: "planner",
            5: "generator",
            6: "validator + tools" if self.enable_validator else "tools",
            7: "tools",
        }
        return executor_labels.get(step_index, "unknown")

    def _print_outcome(self, operation_index: int, outcome: StepOutcome) -> None:
        """统一打印单步结果。"""
        print(f"\n 💭 Thought:")
        print(outcome.thought)
        print(f"\n 🔧 Action: {outcome.action}")
        print(f"\n 🔍 Observation:")
        print(outcome.observation)
        print(f"\n ✅ Step Result:")
        print(outcome.result)
        print(f"\n ⏱️ Step Duration:")
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
        """把各阶段结构化输出写入日志文件。

        这些日志主要用于调试 LLM 输出质量和排查阶段间的数据传递问题。
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agent_name": agent_name,
            "payload": payload,
        }
        with self.log_file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, indent=2))
            file.write("\n\n")
