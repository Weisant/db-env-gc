"""结构化状态对象。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _ensure_str(value: Any, field_name: str, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    return value.strip()


def _ensure_dict_of_str(value: Any, field_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        normalized[str(key).strip()] = str(item).strip()
    return normalized


def _ensure_list_of_str(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return [str(item).strip() for item in value if str(item).strip()]


@dataclass
class TaskInput:
    """标准化后的用户输入。"""

    db_type: str
    version: str
    port: str
    database: str
    username: str
    password: str
    root_password: str
    project_name: str
    config: dict[str, str]
    notes: list[str]
    raw_request: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskInput":
        return cls(
            db_type=_ensure_str(data.get("db_type"), "db_type"),
            version=_ensure_str(data.get("version"), "version"),
            port=_ensure_str(data.get("port"), "port"),
            database=_ensure_str(data.get("database"), "database"),
            username=_ensure_str(data.get("username"), "username"),
            password=_ensure_str(data.get("password"), "password"),
            root_password=_ensure_str(data.get("root_password"), "root_password"),
            project_name=_ensure_str(data.get("project_name"), "project_name"),
            config=_ensure_dict_of_str(data.get("config"), "config"),
            notes=_ensure_list_of_str(data.get("notes"), "notes"),
            raw_request=_ensure_str(data.get("raw_request"), "raw_request"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EnvSpec:
    """LLM 生成的环境规划规格。"""

    project_name: str
    db_type: str
    version: str
    objective: str
    suggested_files: list[str]
    constraints: list[str]
    assumptions: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvSpec":
        return cls(
            project_name=_ensure_str(data.get("project_name"), "project_name"),
            db_type=_ensure_str(data.get("db_type"), "db_type"),
            version=_ensure_str(data.get("version"), "version"),
            objective=_ensure_str(data.get("objective"), "objective"),
            suggested_files=_ensure_list_of_str(
                data.get("suggested_files"), "suggested_files"
            ),
            constraints=_ensure_list_of_str(data.get("constraints"), "constraints"),
            assumptions=_ensure_list_of_str(data.get("assumptions"), "assumptions"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GeneratedFile:
    """最终写入磁盘的文件。"""

    path: str
    purpose: str
    content: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeneratedFile":
        return cls(
            path=_ensure_str(data.get("path"), "files[].path"),
            purpose=_ensure_str(data.get("purpose"), "files[].purpose"),
            content=_ensure_str(data.get("content"), "files[].content"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectArtifacts:
    """项目产物。"""

    project_name: str
    files: list[GeneratedFile]
    run_instructions: list[str]
    summary: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectArtifacts":
        files = data.get("files") or []
        if not isinstance(files, list):
            raise ValueError("files must be a list.")
        return cls(
            project_name=_ensure_str(data.get("project_name"), "project_name"),
            files=[GeneratedFile.from_dict(item) for item in files],
            run_instructions=_ensure_list_of_str(
                data.get("run_instructions"), "run_instructions"
            ),
            summary=_ensure_str(data.get("summary"), "summary"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "files": [file.to_dict() for file in self.files],
            "run_instructions": self.run_instructions,
            "summary": self.summary,
        }


@dataclass
class ValidationReport:
    """校验结果。"""

    passed: bool
    findings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repair_instructions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ValidationReport":
        passed_value = data.get("passed")
        if not isinstance(passed_value, bool):
            raise ValueError("passed must be a boolean.")
        return cls(
            passed=passed_value,
            findings=_ensure_list_of_str(data.get("findings"), "findings"),
            warnings=_ensure_list_of_str(data.get("warnings"), "warnings"),
            repair_instructions=_ensure_list_of_str(
                data.get("repair_instructions"), "repair_instructions"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineResult:
    """一次完整运行的汇总。"""

    run_dir: Path
    task: TaskInput
    env_spec: EnvSpec
    artifacts: ProjectArtifacts
    validation: ValidationReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_dir": str(self.run_dir),
            "task": self.task.to_dict(),
            "env_spec": self.env_spec.to_dict(),
            "artifacts": self.artifacts.to_dict(),
            "validation": self.validation.to_dict(),
        }
