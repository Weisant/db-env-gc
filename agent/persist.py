"""项目落盘工具。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.models import EnvSpec, PipelineResult, ProjectArtifacts, TaskInput, ValidationReport


def persist_result(
    output_root: Path,
    task: TaskInput,
    env_spec: EnvSpec,
    artifacts: ProjectArtifacts,
    validation: ValidationReport,
) -> PipelineResult:
    """将本次运行结果落盘到输出目录。"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / f"{timestamp}-{env_spec.project_name}"
    run_dir.mkdir(parents=True, exist_ok=True)

    for file in artifacts.files:
        target = run_dir / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.content, encoding="utf-8")

    state_dir = run_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "task.json").write_text(
        json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (state_dir / "env_spec.json").write_text(
        json.dumps(env_spec.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (state_dir / "artifacts.json").write_text(
        json.dumps(artifacts.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (state_dir / "validation.json").write_text(
        json.dumps(validation.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return PipelineResult(
        run_dir=run_dir,
        task=task,
        env_spec=env_spec,
        artifacts=artifacts,
        validation=validation,
    )
