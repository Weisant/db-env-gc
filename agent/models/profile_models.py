"""复现画像与证据相关的数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .utils import (
    _ensure_bool,
    _ensure_dict_of_str,
    _ensure_list_of_dict,
    _ensure_list_of_str,
    _ensure_str,
)


@dataclass
class EvidenceItem:
    """外部证据条目。"""

    source_type: str
    source_url: str
    title: str
    published_at: str
    reliability: str
    snippet: str
    claims: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceItem":
        """从字典恢复单条外部证据。"""
        return cls(
            source_type=_ensure_str(data.get("source_type"), "source_type"),
            source_url=_ensure_str(data.get("source_url"), "source_url"),
            title=_ensure_str(data.get("title"), "title"),
            published_at=_ensure_str(data.get("published_at"), "published_at"),
            reliability=_ensure_str(data.get("reliability"), "reliability"),
            snippet=_ensure_str(data.get("snippet"), "snippet"),
            claims=_ensure_list_of_str(data.get("claims"), "claims"),
        )

    def to_dict(self) -> dict[str, Any]:
        """把外部证据对象转回字典。"""
        return asdict(self)


@dataclass
class ArtifactRequirement:
    """复现画像中的单个制品要求。"""

    name: str
    kind: str
    source: str
    identifier: str
    version_constraint: str
    provenance_constraints: list[str]
    mandatory: bool
    notes: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRequirement":
        """从字典恢复单条制品需求。"""
        return cls(
            name=_ensure_str(data.get("name"), "name"),
            kind=_ensure_str(data.get("kind"), "kind"),
            source=_ensure_str(data.get("source"), "source"),
            identifier=_ensure_str(data.get("identifier"), "identifier"),
            version_constraint=_ensure_str(
                data.get("version_constraint"), "version_constraint"
            ),
            provenance_constraints=_ensure_list_of_str(
                data.get("provenance_constraints"), "provenance_constraints"
            ),
            mandatory=_ensure_bool(data.get("mandatory"), "mandatory", default=True),
            notes=_ensure_list_of_str(data.get("notes"), "notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        """把制品需求对象转回字典。"""
        return asdict(self)


@dataclass
class VersionPolicy:
    """复现画像中的通用版本约束策略。"""

    requested_version: str
    min_version: str
    max_version: str
    fixed_versions: list[str]
    excluded_versions: list[str]
    notes: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VersionPolicy":
        """从字典恢复复现画像中的版本策略。"""
        return cls(
            requested_version=_ensure_str(
                data.get("requested_version"), "version_policy.requested_version"
            ),
            min_version=_ensure_str(
                data.get("min_version"), "version_policy.min_version"
            ),
            max_version=_ensure_str(
                data.get("max_version"), "version_policy.max_version"
            ),
            fixed_versions=_ensure_list_of_str(
                data.get("fixed_versions"), "version_policy.fixed_versions"
            ),
            excluded_versions=_ensure_list_of_str(
                data.get("excluded_versions"), "version_policy.excluded_versions"
            ),
            notes=_ensure_list_of_str(data.get("notes"), "version_policy.notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        """把版本策略对象转回字典。"""
        return asdict(self)


@dataclass
class CapabilityConstraint:
    """版本相关的能力约束。"""

    capability: str
    min_version: str
    max_version: str
    notes: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityConstraint":
        """从字典恢复能力约束对象。"""
        return cls(
            capability=_ensure_str(
                data.get("capability"), "capability_constraints[].capability"
            ),
            min_version=_ensure_str(
                data.get("min_version"), "capability_constraints[].min_version"
            ),
            max_version=_ensure_str(
                data.get("max_version"), "capability_constraints[].max_version"
            ),
            notes=_ensure_list_of_str(
                data.get("notes"), "capability_constraints[].notes"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """把能力约束对象转回字典。"""
        return asdict(self)


@dataclass
class ReproductionProfile:
    """证据驱动的复现约束画像。"""

    cve_id: str
    confidence: str
    evidence_db_type: str
    evidence_version_scope: str
    input_conflict_detected: bool
    input_conflict_reason: str
    artifact_semantics: str
    requires_build_time_configuration: bool
    version_policy: VersionPolicy
    required_artifacts: list[ArtifactRequirement]
    capability_constraints: list[CapabilityConstraint]
    required_configuration: dict[str, str]
    required_setup_steps: list[str]
    forbidden_choices: list[str]
    open_questions: list[str]
    notes: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReproductionProfile":
        """从字典恢复完整的复现约束画像。"""
        return cls(
            cve_id=_ensure_str(data.get("cve_id"), "cve_id"),
            confidence=_ensure_str(data.get("confidence"), "confidence"),
            evidence_db_type=_ensure_str(
                data.get("evidence_db_type"), "evidence_db_type"
            ),
            evidence_version_scope=_ensure_str(
                data.get("evidence_version_scope"), "evidence_version_scope"
            ),
            input_conflict_detected=_ensure_bool(
                data.get("input_conflict_detected"),
                "input_conflict_detected",
                default=False,
            ),
            input_conflict_reason=_ensure_str(
                data.get("input_conflict_reason"), "input_conflict_reason"
            ),
            artifact_semantics=_ensure_str(
                data.get("artifact_semantics"), "artifact_semantics"
            ),
            requires_build_time_configuration=_ensure_bool(
                data.get("requires_build_time_configuration"),
                "requires_build_time_configuration",
                default=False,
            ),
            version_policy=VersionPolicy.from_dict(
                data.get("version_policy")
                if isinstance(data.get("version_policy"), dict)
                else {}
            ),
            required_artifacts=[
                ArtifactRequirement.from_dict(item)
                for item in _ensure_list_of_dict(
                    data.get("required_artifacts"), "required_artifacts"
                )
            ],
            capability_constraints=[
                CapabilityConstraint.from_dict(item)
                for item in _ensure_list_of_dict(
                    data.get("capability_constraints"), "capability_constraints"
                )
            ],
            required_configuration=_ensure_dict_of_str(
                data.get("required_configuration"), "required_configuration"
            ),
            required_setup_steps=_ensure_list_of_str(
                data.get("required_setup_steps"), "required_setup_steps"
            ),
            forbidden_choices=_ensure_list_of_str(
                data.get("forbidden_choices"), "forbidden_choices"
            ),
            open_questions=_ensure_list_of_str(
                data.get("open_questions"), "open_questions"
            ),
            notes=_ensure_list_of_str(data.get("notes"), "notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        """把复现约束画像转回字典。"""
        return {
            "cve_id": self.cve_id,
            "confidence": self.confidence,
            "evidence_db_type": self.evidence_db_type,
            "evidence_version_scope": self.evidence_version_scope,
            "input_conflict_detected": self.input_conflict_detected,
            "input_conflict_reason": self.input_conflict_reason,
            "artifact_semantics": self.artifact_semantics,
            "requires_build_time_configuration": self.requires_build_time_configuration,
            "version_policy": self.version_policy.to_dict(),
            "required_artifacts": [item.to_dict() for item in self.required_artifacts],
            "capability_constraints": [
                item.to_dict() for item in self.capability_constraints
            ],
            "required_configuration": self.required_configuration,
            "required_setup_steps": self.required_setup_steps,
            "forbidden_choices": self.forbidden_choices,
            "open_questions": self.open_questions,
            "notes": self.notes,
        }
