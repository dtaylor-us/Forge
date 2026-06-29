"""Memory data models for the Engineering Memory subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MemoryType(StrEnum):
    plan = "plan"
    workset = "workset"
    context_bundle = "context_bundle"
    adr = "adr"
    architecture = "architecture"
    bug = "bug"
    decision = "decision"
    investigation = "investigation"
    followup = "followup"


@dataclass
class MemoryItem:
    """A single engineering memory artifact."""

    id: str
    type: MemoryType
    title: str
    created_at: str
    repository: str
    workset: str = ""
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    related_files: list[str] = field(default_factory=list)
    related_plans: list[str] = field(default_factory=list)
    related_worksets: list[str] = field(default_factory=list)
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "title": self.title,
            "created_at": self.created_at,
            "repository": self.repository,
            "workset": self.workset,
            "tags": self.tags,
            "summary": self.summary,
            "related_files": self.related_files,
            "related_plans": self.related_plans,
            "related_worksets": self.related_worksets,
            "source_path": self.source_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryItem:
        return cls(
            id=data["id"],
            type=MemoryType(data["type"]),
            title=data["title"],
            created_at=data["created_at"],
            repository=data["repository"],
            workset=data.get("workset", ""),
            tags=data.get("tags", []),
            summary=data.get("summary", ""),
            related_files=data.get("related_files", []),
            related_plans=data.get("related_plans", []),
            related_worksets=data.get("related_worksets", []),
            source_path=data.get("source_path", ""),
        )
