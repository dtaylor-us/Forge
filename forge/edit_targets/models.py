"""Data models for deterministic editable targets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EditableConfidence = Literal["primary", "related", "allowed_context"]


@dataclass(frozen=True)
class EditableTarget:
    """A repository file the model is allowed to modify."""

    path: str
    reason: str
    confidence: EditableConfidence
    required: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "path": self.path,
            "reason": self.reason,
            "confidence": self.confidence,
            "required": self.required,
        }


@dataclass(frozen=True)
class EditableTargetSet:
    """Deterministic set of files approved for modification."""

    task: str
    workset_name: str
    targets: list[EditableTarget]
    missing_required: list[str] | None = None

    def allowed_paths(self) -> set[str]:
        """Return normalized repository-relative paths that may be edited."""
        return {_normalize_path(target.path) for target in self.targets}

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "task": self.task,
            "workset_name": self.workset_name,
            "targets": [target.to_dict() for target in self.targets],
            "missing_required": list(self.missing_required or []),
        }


def _normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/").lstrip("./")
