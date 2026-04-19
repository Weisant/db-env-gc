"""状态文件工具。

这些函数负责把一次运行过程中的关键结构化对象持久化到 `state/` 目录中，
便于后续回溯、调试和对比。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.models import (
    ArtifactFact,
    ArtifactPlan,
    EnvSpec,
    EvidenceItem,
    FinalVersionDecision,
    ProjectArtifacts,
    ReproductionProfile,
    ResolvedTask,
    TaskInput,
    ValidationReport,
)
from tools.file_tools import ensure_directory, write_file


def write_pipeline_state(
    run_dir: Path,
    task: TaskInput,
    resolved_task: ResolvedTask,
    final_version_decision: FinalVersionDecision,
    evidence: list[EvidenceItem],
    reproduction_profile: ReproductionProfile,
    artifact_facts: list[ArtifactFact],
    artifact_plan: ArtifactPlan,
    env_spec: EnvSpec,
    artifacts: ProjectArtifacts,
    validation: ValidationReport,
) -> list[str]:
    """把流水线中的关键对象统一写入 `state/` 目录。"""
    state_dir = run_dir / "state"
    ensure_directory(state_dir)

    state_payloads = {
        "task.json": task.to_dict(),
        "resolved_task.json": resolved_task.to_dict(),
        "final_version_decision.json": final_version_decision.to_dict(),
        "evidence.json": [item.to_dict() for item in evidence],
        "reproduction_profile.json": reproduction_profile.to_dict(),
        "artifact_facts.json": [item.to_dict() for item in artifact_facts],
        "artifact_plan.json": artifact_plan.to_dict(),
        "env_spec.json": env_spec.to_dict(),
        "artifacts.json": artifacts.to_dict(),
        "validation.json": validation.to_dict(),
    }

    written_files: list[str] = []
    for filename, payload in state_payloads.items():
        write_file(
            state_dir / filename,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        written_files.append(f"state/{filename}")
    return written_files
