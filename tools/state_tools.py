"""状态文件工具。

这些函数负责把一次运行过程中的关键结构化对象持久化到 `state/` 目录中，
便于后续回溯、调试和对比。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.models import EnvSpec, ImageResolution, ProjectArtifacts, TaskInput, ValidationReport, VersionResolution
from tools.file_tools import ensure_directory, write_file


def write_pipeline_state(
    run_dir: Path,
    task: TaskInput,
    version_resolution: VersionResolution,
    image_resolution: ImageResolution,
    env_spec: EnvSpec,
    artifacts: ProjectArtifacts,
    validation: ValidationReport,
) -> list[str]:
    """把流水线中的关键对象统一写入 `state/` 目录。"""
    state_dir = run_dir / "state"
    ensure_directory(state_dir)

    state_payloads = {
        "task.json": task.to_dict(),
        "version_resolution.json": version_resolution.to_dict(),
        "image_resolution.json": image_resolution.to_dict(),
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
