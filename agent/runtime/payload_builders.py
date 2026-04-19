"""公共 payload 构造器。

把 planner / generator / validator 中重复的摘要构造逻辑集中到这里，
减少各阶段之间的重复代码和规则漂移。
"""

from __future__ import annotations

from agent.models import (
    ArtifactFact,
    ArtifactPlan,
    EnvSpec,
    ProjectSnapshot,
    ReproductionProfile,
    ResolvedTask,
    TaskInput,
)


def compact_dict(data: dict[str, object]) -> dict[str, object]:
    """删除空值字段，减少 payload 体积。"""
    compacted: dict[str, object] = {}
    for key, value in data.items():
        if value in ("", [], {}, None):
            continue
        compacted[key] = value
    return compacted


def build_public_version_policy_summary(version_policy) -> dict[str, object]:
    """构造可安全暴露给下游阶段的版本策略摘要。"""
    return compact_dict(
        {
            "requested_version": version_policy.requested_version,
            "min_version": version_policy.min_version,
            "max_version": version_policy.max_version,
            "fixed_versions": version_policy.fixed_versions,
            "excluded_versions": version_policy.excluded_versions,
            "notes": version_policy.notes[:3],
        }
    )


def build_resolved_task_summary(
    task: TaskInput,
    resolved_task: ResolvedTask,
) -> dict[str, object]:
    """把最终决议任务压缩成下游阶段直接可用的摘要。"""
    return compact_dict(
        {
            "cve_id": task.cve_id,
            "db_type": resolved_task.db_type or task.db_type,
            "requested_version": resolved_task.requested_version,
            "final_version": resolved_task.final_version,
            "version": resolved_task.final_version,
            "project_name": resolved_task.project_name,
            "version_source": resolved_task.version_source,
            "version_reason": resolved_task.version_reason,
            "delivery_strategy": resolved_task.delivery_strategy,
            "delivery_reason": resolved_task.delivery_reason,
            "port": task.port,
            "database": task.database,
            "username": task.username,
            "password": task.password,
            "root_password": task.root_password,
            "config": task.config,
            "notes": task.notes[:4],
        }
    )


def build_profile_summary(
    reproduction_profile: ReproductionProfile,
    *,
    artifact_limit: int = 5,
    capability_limit: int = 6,
    note_limit: int = 4,
) -> dict[str, object]:
    """裁剪复现画像，只保留关键约束。"""
    return compact_dict(
        {
            "cve_id": reproduction_profile.cve_id,
            "confidence": reproduction_profile.confidence,
            "evidence_db_type": reproduction_profile.evidence_db_type,
            "evidence_version_scope": reproduction_profile.evidence_version_scope,
            "input_conflict_detected": reproduction_profile.input_conflict_detected,
            "input_conflict_reason": reproduction_profile.input_conflict_reason,
            "artifact_semantics": reproduction_profile.artifact_semantics,
            "requires_build_time_configuration": reproduction_profile.requires_build_time_configuration,
            "version_policy": build_public_version_policy_summary(
                reproduction_profile.version_policy
            ),
            "required_artifacts": [
                compact_dict(
                    {
                        "name": item.name,
                        "kind": item.kind,
                        "source": item.source,
                        "identifier": item.identifier,
                        "version_constraint": item.version_constraint,
                        "mandatory": item.mandatory,
                        "notes": item.notes[:2],
                    }
                )
                for item in reproduction_profile.required_artifacts[:artifact_limit]
            ],
            "capability_constraints": [
                compact_dict(item.to_dict())
                for item in reproduction_profile.capability_constraints[:capability_limit]
            ],
            "required_configuration": reproduction_profile.required_configuration,
            "required_setup_steps": reproduction_profile.required_setup_steps[
                :capability_limit
            ],
            "forbidden_choices": reproduction_profile.forbidden_choices[:capability_limit],
            "open_questions": reproduction_profile.open_questions[:note_limit],
            "notes": reproduction_profile.notes[:note_limit],
        }
    )

def build_artifact_fact_summary(
    artifact_facts: list[ArtifactFact],
    *,
    limit: int = 8,
) -> list[dict[str, object]]:
    """把工具层收集到的制品事实压缩成摘要。"""
    summary: list[dict[str, object]] = []
    for item in artifact_facts[:limit]:
        summary.append(
            compact_dict(
                {
                    "fact_type": item.fact_type,
                    "source": item.source,
                    "identifier": item.identifier,
                    "version": item.version,
                    "ref": item.ref,
                    "available": item.available,
                    "notes": item.notes[:2],
                }
            )
        )
    return summary


def build_artifact_plan_summary(artifact_plan: ArtifactPlan) -> dict[str, object]:
    """把制品计划压缩成下游阶段可直接消费的摘要。"""
    return compact_dict(
        {
            "project_name": artifact_plan.project_name,
            "effective_db_type": artifact_plan.effective_db_type,
            "delivery_strategy": artifact_plan.delivery_strategy,
            "primary_artifact_kind": artifact_plan.primary_artifact_kind,
            "selected_version": artifact_plan.selected_version,
            "version_source": artifact_plan.version_source,
            "selected_identifier": artifact_plan.selected_identifier,
            "selected_image": artifact_plan.selected_image,
            "selected_download_url": artifact_plan.selected_download_url,
            "requires_dockerfile": artifact_plan.requires_dockerfile,
            "reason": artifact_plan.reason,
            "confidence": artifact_plan.confidence,
            "notes": artifact_plan.notes[:3],
        }
    )


def build_runtime_task_summary(
    task: TaskInput,
    resolved_task: ResolvedTask,
    env_spec: EnvSpec,
) -> dict[str, object]:
    """生成运行性校验阶段使用的任务与环境摘要。"""
    return compact_dict(
        {
            "db_type": resolved_task.db_type or task.db_type,
            "project_name": resolved_task.project_name,
            "port": task.port,
            "database": task.database,
            "username": task.username,
            "requires_dockerfile": env_spec.requires_dockerfile,
            "base_image": env_spec.base_image,
            "install_method": env_spec.install_method,
            "deployment_approach": env_spec.deployment_approach,
            "suggested_files": env_spec.suggested_files,
            "requested_version": resolved_task.requested_version,
            "final_version": resolved_task.final_version,
            "version": resolved_task.final_version,
        }
    )


def build_runtime_snapshot_summary(snapshot: ProjectSnapshot) -> dict[str, object]:
    """从磁盘快照里筛出运行性校验最关心的文件内容。"""
    interesting_paths = (
        "docker-compose.yml",
        "compose.yml",
        "compose.yaml",
        ".env.example",
        "Dockerfile",
        "README.md",
    )
    summarized_files = []
    for snapshot_file in snapshot.files:
        if (
            snapshot_file.path in interesting_paths
            or snapshot_file.path.startswith("config/")
            or snapshot_file.path.startswith("init/")
            or snapshot_file.path.endswith(".conf")
            or snapshot_file.path.endswith(".sql")
            or snapshot_file.path.endswith(".sh")
        ):
            summarized_files.append(
                {
                    "path": snapshot_file.path,
                    "content": truncate_snapshot_content(
                        snapshot_file.path, snapshot_file.content
                    ),
                }
            )
    return {
        "root_dir": str(snapshot.root_dir),
        "files": summarized_files,
    }


def truncate_snapshot_content(path: str, content: str) -> str:
    """按文件类型截断内容，避免校验 payload 过大。"""
    if path in {"docker-compose.yml", "compose.yml", "compose.yaml", "Dockerfile", ".env.example"}:
        return content[:4000]
    if path == "README.md":
        return content[:2000]
    return content[:1600]
