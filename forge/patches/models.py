"""Patch metadata models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Patch:
    """Metadata and validation result for a saved patch file."""

    name: str
    path: Path
    size_bytes: int
    valid: bool
    validation_errors: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "name": self.name,
            "path": str(self.path),
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
            "valid": self.valid,
            "validation_errors": self.validation_errors,
            "affected_files": self.affected_files,
        }
