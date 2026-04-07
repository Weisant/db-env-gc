"""结构化状态对象。

这个模块定义了 agent 之间交换数据时使用的统一结构。
所有 LLM 输出在进入主流程前，都会先通过这些 dataclass 做一次结构化校验，
这样可以把“模型输出不稳定”的问题尽量限制在边界层。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _ensure_str(value: Any, field_name: str, default: str = "") -> str:
    """把任意值规范成字符串。

    这里显式做类型校验，是为了尽早发现模型返回了非预期结构。
    """
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    return value.strip()


def _ensure_dict_of_str(value: Any, field_name: str) -> dict[str, str]:
    """把任意字典规范成 `str -> str` 结构。"""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        normalized[str(key).strip()] = str(item).strip()
    return normalized


def _ensure_list_of_str(value: Any, field_name: str) -> list[str]:
    """把任意列表规范成字符串列表。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return [str(item).strip() for item in value if str(item).strip()]


def _ensure_bool(value: Any, field_name: str, default: bool = False) -> bool:
    """把任意值规范成布尔值。"""
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean.")
    return value


@dataclass
class TaskInput:
    """标准化后的用户输入。

    parser agent 的职责，就是把原始自然语言请求整理为这个对象。
    后续 planner / generator / validator 都基于它工作。
    """

    cve_id: str
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
            cve_id=_ensure_str(data.get("cve_id"), "cve_id"),
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
    """LLM 生成的环境规划规格。

    这里保留 `EnvSpec` 这个名字，是为了表达“环境规划结果”，
    而不是模板、渲染规则或硬编码策略。
    """

    project_name: str
    cve_id: str
    db_type: str
    version: str
    objective: str
    image_strategy: str
    image_ref: str
    requires_dockerfile: bool
    suggested_files: list[str]
    constraints: list[str]
    assumptions: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvSpec":
        return cls(
            project_name=_ensure_str(data.get("project_name"), "project_name"),
            cve_id=_ensure_str(data.get("cve_id"), "cve_id"),
            db_type=_ensure_str(data.get("db_type"), "db_type"),
            version=_ensure_str(data.get("version"), "version"),
            objective=_ensure_str(data.get("objective"), "objective"),
            image_strategy=_ensure_str(data.get("image_strategy"), "image_strategy"),
            image_ref=_ensure_str(data.get("image_ref"), "image_ref"),
            requires_dockerfile=_ensure_bool(
                data.get("requires_dockerfile"), "requires_dockerfile"
            ),
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
    """单个待写入磁盘的文件对象。"""

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
    """generator agent 输出的完整项目文件集合。"""

    project_name: str
    cve_id: str
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
            cve_id=_ensure_str(data.get("cve_id"), "cve_id"),
            files=[GeneratedFile.from_dict(item) for item in files],
            run_instructions=_ensure_list_of_str(
                data.get("run_instructions"), "run_instructions"
            ),
            summary=_ensure_str(data.get("summary"), "summary"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "cve_id": self.cve_id,
            "files": [file.to_dict() for file in self.files],
            "run_instructions": self.run_instructions,
            "summary": self.summary,
        }


@dataclass
class ValidationReport:
    """validator agent 输出的校验结果。

    `repair_instructions` 用来承接“可自动修复”的问题说明。
    当前修复动作已经并入 validator 模块内部，而不再由独立的修复阶段负责。
    """

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
class VersionResolution:
    """数据库版本来源解析结果。

    这个对象由 tools 层基于项目内置的官方源码源规则得到，
    用来判断“请求的数据库版本本身是否真实存在”。
    """

    db_type: str
    requested_version: str
    source_name: str
    source_url: str
    version_exists: bool
    matched_version: str
    matched_url: str
    lookup_strategy: str
    availability: str
    checked_sources: list[str]
    checked_candidates: list[str]
    notes: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VersionResolution":
        return cls(
            db_type=_ensure_str(data.get("db_type"), "db_type"),
            requested_version=_ensure_str(data.get("requested_version"), "requested_version"),
            source_name=_ensure_str(data.get("source_name"), "source_name"),
            source_url=_ensure_str(data.get("source_url"), "source_url"),
            version_exists=_ensure_bool(data.get("version_exists"), "version_exists"),
            matched_version=_ensure_str(data.get("matched_version"), "matched_version"),
            matched_url=_ensure_str(data.get("matched_url"), "matched_url"),
            lookup_strategy=_ensure_str(data.get("lookup_strategy"), "lookup_strategy"),
            availability=_ensure_str(data.get("availability"), "availability"),
            checked_sources=_ensure_list_of_str(
                data.get("checked_sources"), "checked_sources"
            ),
            checked_candidates=_ensure_list_of_str(
                data.get("checked_candidates"), "checked_candidates"
            ),
            notes=_ensure_list_of_str(data.get("notes"), "notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImageResolution:
    """镜像来源解析结果。

    这个对象由 tools 层基于 Docker Hub 查询得到，
    供 planner / generator / validator 决定应走 `image:` 还是 `Dockerfile` 分支。
    """

    db_type: str
    requested_version: str
    namespace: str
    repository: str
    matched_tag: str
    image_ref: str
    strategy: str
    availability: str
    checked_candidates: list[str]
    notes: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageResolution":
        return cls(
            db_type=_ensure_str(data.get("db_type"), "db_type"),
            requested_version=_ensure_str(data.get("requested_version"), "requested_version"),
            namespace=_ensure_str(data.get("namespace"), "namespace"),
            repository=_ensure_str(data.get("repository"), "repository"),
            matched_tag=_ensure_str(data.get("matched_tag"), "matched_tag"),
            image_ref=_ensure_str(data.get("image_ref"), "image_ref"),
            strategy=_ensure_str(data.get("strategy"), "strategy"),
            availability=_ensure_str(data.get("availability"), "availability"),
            checked_candidates=_ensure_list_of_str(
                data.get("checked_candidates"), "checked_candidates"
            ),
            notes=_ensure_list_of_str(data.get("notes"), "notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineResult:
    """一次完整运行的汇总结果。"""

    run_dir: Path
    task: TaskInput
    version_resolution: VersionResolution
    image_resolution: ImageResolution
    env_spec: EnvSpec
    artifacts: ProjectArtifacts
    validation: ValidationReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_dir": str(self.run_dir),
            "task": self.task.to_dict(),
            "version_resolution": self.version_resolution.to_dict(),
            "image_resolution": self.image_resolution.to_dict(),
            "env_spec": self.env_spec.to_dict(),
            "artifacts": self.artifacts.to_dict(),
            "validation": self.validation.to_dict(),
        }


@dataclass
class ProjectSnapshotFile:
    """磁盘快照中的单个文本文件。

    validator 不再只校验内存中的 `ProjectArtifacts`，而是会读取真实落盘后的文件快照。
    """

    path: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectSnapshot:
    """项目目录在某一时刻的真实磁盘快照。"""

    root_dir: Path
    files: list[ProjectSnapshotFile]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_dir": str(self.root_dir),
            "files": [file.to_dict() for file in self.files],
        }
