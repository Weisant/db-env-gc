"""项目生成、制品计划与状态汇总相关的数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .profile_models import EvidenceItem, ReproductionProfile
from .task_models import ResolvedTask, TaskInput
from .utils import _ensure_bool, _ensure_list_of_str, _ensure_str


@dataclass
class EnvSpec:
    """LLM 生成的环境规划规格。"""

    project_name: str
    cve_id: str
    db_type: str
    version: str
    objective: str
    deployment_approach: str
    base_image: str
    install_method: str
    requires_dockerfile: bool
    suggested_files: list[str]
    constraints: list[str]
    assumptions: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvSpec":
        """从规划阶段输出恢复环境规划对象。"""
        return cls(
            project_name=_ensure_str(data.get("project_name"), "project_name"),
            cve_id=_ensure_str(data.get("cve_id"), "cve_id"),
            db_type=_ensure_str(data.get("db_type"), "db_type"),
            version=_ensure_str(data.get("version"), "version"),
            objective=_ensure_str(data.get("objective"), "objective"),
            deployment_approach=_ensure_str(
                data.get("deployment_approach"), "deployment_approach"
            ),
            base_image=_ensure_str(data.get("base_image"), "base_image"),
            install_method=_ensure_str(data.get("install_method"), "install_method"),
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
        """把环境规划对象转回字典。"""
        return asdict(self)


@dataclass
class GeneratedFile:
    """单个待写入磁盘的文件对象。"""

    path: str
    purpose: str
    content: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeneratedFile":
        """从字典恢复单个生成文件对象。"""
        return cls(
            path=_ensure_str(data.get("path"), "files[].path"),
            purpose=_ensure_str(data.get("purpose"), "files[].purpose"),
            content=_ensure_str(data.get("content"), "files[].content"),
        )

    def to_dict(self) -> dict[str, Any]:
        """把单个生成文件对象转回字典。"""
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
        """从 generator 输出恢复完整项目文件集合。"""
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
        """把完整项目文件集合转回可序列化结构。"""
        return {
            "project_name": self.project_name,
            "cve_id": self.cve_id,
            "files": [file.to_dict() for file in self.files],
            "run_instructions": self.run_instructions,
            "summary": self.summary,
        }


@dataclass
class ValidationReport:
    """validator agent 输出的校验结果。"""

    passed: bool
    findings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repair_instructions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ValidationReport":
        """从 validator 输出恢复校验报告。"""
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
        """把校验报告转回字典。"""
        return asdict(self)


@dataclass
class ArtifactFact:
    """工具层收集到的外部制品事实。"""

    fact_type: str
    source: str
    identifier: str
    version: str
    ref: str
    available: bool
    notes: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactFact":
        """从字典恢复单条制品事实。"""
        return cls(
            fact_type=_ensure_str(data.get("fact_type"), "fact_type"),
            source=_ensure_str(data.get("source"), "source"),
            identifier=_ensure_str(data.get("identifier"), "identifier"),
            version=_ensure_str(data.get("version"), "version"),
            ref=_ensure_str(data.get("ref"), "ref"),
            available=_ensure_bool(data.get("available"), "available"),
            notes=_ensure_list_of_str(data.get("notes"), "notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        """把制品事实对象转回字典。"""
        return asdict(self)


@dataclass
class ArtifactPlan:
    """LLM 基于画像和事实生成的制品计划。"""

    project_name: str
    effective_db_type: str
    delivery_strategy: str
    primary_artifact_kind: str
    selected_version: str
    version_source: str
    selected_identifier: str
    selected_image: str
    selected_download_url: str
    requires_dockerfile: bool
    reason: str
    confidence: str
    notes: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactPlan":
        """从字典恢复结构化制品计划。"""
        return cls(
            project_name=_ensure_str(
                data.get("project_name"), "artifact_plan.project_name"
            ),
            effective_db_type=_ensure_str(
                data.get("effective_db_type"),
                "artifact_plan.effective_db_type",
            ),
            delivery_strategy=_ensure_str(
                data.get("delivery_strategy"), "artifact_plan.delivery_strategy"
            ),
            primary_artifact_kind=_ensure_str(
                data.get("primary_artifact_kind"),
                "artifact_plan.primary_artifact_kind",
            ),
            selected_version=_ensure_str(
                data.get("selected_version"), "artifact_plan.selected_version"
            ),
            version_source=_ensure_str(
                data.get("version_source"), "artifact_plan.version_source"
            ),
            selected_identifier=_ensure_str(
                data.get("selected_identifier"),
                "artifact_plan.selected_identifier",
            ),
            selected_image=_ensure_str(
                data.get("selected_image"), "artifact_plan.selected_image"
            ),
            selected_download_url=_ensure_str(
                data.get("selected_download_url"),
                "artifact_plan.selected_download_url",
            ),
            requires_dockerfile=_ensure_bool(
                data.get("requires_dockerfile"),
                "artifact_plan.requires_dockerfile",
            ),
            reason=_ensure_str(data.get("reason"), "artifact_plan.reason"),
            confidence=_ensure_str(data.get("confidence"), "artifact_plan.confidence"),
            notes=_ensure_list_of_str(data.get("notes"), "artifact_plan.notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        """把制品计划对象转回字典。"""
        return asdict(self)


@dataclass
class FinalVersionDecision:
    """制品计划阶段收敛出的最终版本决议。"""

    project_name: str
    effective_db_type: str
    requested_version: str
    final_version: str
    version_source: str
    version_reason: str
    delivery_strategy: str
    delivery_reason: str
    blocked_versions: list[str]
    selection_confidence: str
    primary_requirement_name: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FinalVersionDecision":
        """从字典恢复唯一最终版本决议。"""
        return cls(
            project_name=_ensure_str(
                data.get("project_name"), "final_version_decision.project_name"
            ),
            effective_db_type=_ensure_str(
                data.get("effective_db_type"),
                "final_version_decision.effective_db_type",
            ),
            requested_version=_ensure_str(
                data.get("requested_version"), "final_version_decision.requested_version"
            ),
            final_version=_ensure_str(
                data.get("final_version"), "final_version_decision.final_version"
            ),
            version_source=_ensure_str(
                data.get("version_source"), "final_version_decision.version_source"
            ),
            version_reason=_ensure_str(
                data.get("version_reason"), "final_version_decision.version_reason"
            ),
            delivery_strategy=_ensure_str(
                data.get("delivery_strategy"),
                "final_version_decision.delivery_strategy",
            ),
            delivery_reason=_ensure_str(
                data.get("delivery_reason"),
                "final_version_decision.delivery_reason",
            ),
            blocked_versions=_ensure_list_of_str(
                data.get("blocked_versions"), "final_version_decision.blocked_versions"
            ),
            selection_confidence=_ensure_str(
                data.get("selection_confidence"),
                "final_version_decision.selection_confidence",
            ),
            primary_requirement_name=_ensure_str(
                data.get("primary_requirement_name"),
                "final_version_decision.primary_requirement_name",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """把最终版本决议转回字典。"""
        return asdict(self)


@dataclass
class VersionResolution:
    """兼容旧工具链的数据库版本来源解析结果。"""

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
        """从字典恢复旧版版本来源解析结果。"""
        return cls(
            db_type=_ensure_str(data.get("db_type"), "db_type"),
            requested_version=_ensure_str(
                data.get("requested_version"), "requested_version"
            ),
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
        """把旧版版本来源解析结果转回字典。"""
        return asdict(self)


@dataclass
class ImageResolution:
    """兼容旧工具链的镜像来源解析结果。"""

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
        """从字典恢复旧版镜像解析结果。"""
        return cls(
            db_type=_ensure_str(data.get("db_type"), "db_type"),
            requested_version=_ensure_str(
                data.get("requested_version"), "requested_version"
            ),
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
        """把旧版镜像解析结果转回字典。"""
        return asdict(self)


@dataclass
class PipelineResult:
    """一次完整运行的汇总结果。"""

    run_dir: Path
    task: TaskInput
    resolved_task: ResolvedTask
    final_version_decision: FinalVersionDecision
    evidence: list[EvidenceItem]
    reproduction_profile: ReproductionProfile
    artifact_facts: list[ArtifactFact]
    artifact_plan: ArtifactPlan
    env_spec: EnvSpec
    artifacts: ProjectArtifacts
    validation: ValidationReport

    def to_dict(self) -> dict[str, Any]:
        """把整轮流水线结果转回状态落盘结构。"""
        return {
            "run_dir": str(self.run_dir),
            "task": self.task.to_dict(),
            "resolved_task": self.resolved_task.to_dict(),
            "final_version_decision": self.final_version_decision.to_dict(),
            "evidence": [item.to_dict() for item in self.evidence],
            "reproduction_profile": self.reproduction_profile.to_dict(),
            "artifact_facts": [item.to_dict() for item in self.artifact_facts],
            "artifact_plan": self.artifact_plan.to_dict(),
            "env_spec": self.env_spec.to_dict(),
            "artifacts": self.artifacts.to_dict(),
            "validation": self.validation.to_dict(),
        }


@dataclass
class ProjectSnapshotFile:
    """磁盘快照中的单个文本文件。"""

    path: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        """把快照文件对象转回字典。"""
        return asdict(self)


@dataclass
class ProjectSnapshot:
    """项目目录在某一时刻的真实磁盘快照。"""

    root_dir: Path
    files: list[ProjectSnapshotFile]

    def to_dict(self) -> dict[str, Any]:
        """把真实项目快照转回字典。"""
        return {
            "root_dir": str(self.root_dir),
            "files": [file.to_dict() for file in self.files],
        }
