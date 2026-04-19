"""任务与任务决议相关的数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .utils import _ensure_dict_of_str, _ensure_list_of_str, _ensure_str


@dataclass
class TaskInput:
    """标准化后的用户输入。"""

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
    requested_version: str = ""
    effective_version: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskInput":
        """从模型输出或状态文件恢复标准化任务对象。"""
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
            requested_version=_ensure_str(
                data.get("requested_version"),
                "requested_version",
                default=_ensure_str(data.get("version"), "version"),
            ),
            effective_version=_ensure_str(
                data.get("effective_version"),
                "effective_version",
                default=_ensure_str(data.get("version"), "version"),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """把标准化任务对象转回可序列化字典。"""
        return asdict(self)


@dataclass
class ResolvedTask:
    """流水线收敛出的最终任务决议。"""

    cve_id: str
    db_type: str
    requested_version: str
    final_version: str
    project_name: str
    version_source: str
    version_reason: str
    delivery_strategy: str
    delivery_reason: str
    blocked_versions: list[str]
    selection_confidence: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResolvedTask":
        """从字典恢复最终决议任务对象。"""
        return cls(
            cve_id=_ensure_str(data.get("cve_id"), "resolved_task.cve_id"),
            db_type=_ensure_str(data.get("db_type"), "resolved_task.db_type"),
            requested_version=_ensure_str(
                data.get("requested_version"), "resolved_task.requested_version"
            ),
            final_version=_ensure_str(
                data.get("final_version"), "resolved_task.final_version"
            ),
            project_name=_ensure_str(
                data.get("project_name"), "resolved_task.project_name"
            ),
            version_source=_ensure_str(
                data.get("version_source"), "resolved_task.version_source"
            ),
            version_reason=_ensure_str(
                data.get("version_reason"), "resolved_task.version_reason"
            ),
            delivery_strategy=_ensure_str(
                data.get("delivery_strategy"), "resolved_task.delivery_strategy"
            ),
            delivery_reason=_ensure_str(
                data.get("delivery_reason"), "resolved_task.delivery_reason"
            ),
            blocked_versions=_ensure_list_of_str(
                data.get("blocked_versions"), "resolved_task.blocked_versions"
            ),
            selection_confidence=_ensure_str(
                data.get("selection_confidence"),
                "resolved_task.selection_confidence",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """把最终决议任务对象转回字典。"""
        return asdict(self)
