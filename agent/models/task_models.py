"""Task input related data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .utils import _ensure_dict_of_str, _ensure_list_of_str, _ensure_str


@dataclass
class TaskInput:
    """Standardized user input."""

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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskInput":
        """Restore a standardized task object from model output or a state file."""
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
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert a standardized task object back to a serializable dictionary."""
        return asdict(self)
