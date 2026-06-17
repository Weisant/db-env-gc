"""Evidence-related data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .utils import _ensure_list_of_str, _ensure_str


@dataclass
class EvidenceItem:
    """External evidence item."""

    source_type: str
    source_url: str
    title: str
    published_at: str
    reliability: str
    snippet: str
    claims: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceItem":
        """Restore one external evidence item from a dictionary."""
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
        """Convert an external evidence object back to a dictionary."""
        return asdict(self)
