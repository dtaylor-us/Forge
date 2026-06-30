"""Data models for the search/replace patch pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchReplaceBlock:
    """A single SEARCH/REPLACE edit targeting one file.

    ``search`` is the exact string to find in the file.
    ``replace`` is the string to substitute in its place.
    Both are multi-line strings without a trailing newline enforced here;
    the applier normalises line endings before comparison.
    """

    file_path: str  # relative to repository root
    search: str
    replace: str


@dataclass(frozen=True)
class BlockApplication:
    """Result of attempting to apply one :class:`SearchReplaceBlock`."""

    block: SearchReplaceBlock
    applied: bool
    error: str | None = None


@dataclass(frozen=True)
class SearchReplaceResult:
    """Aggregate result of applying a full set of SEARCH/REPLACE blocks.

    ``patch_content`` is a git-compatible unified diff string ready to be saved
    as a ``.patch`` file.  It is ``None`` when any block failed to apply.
    ``valid`` mirrors ``bool(patch_content)`` for convenience.
    """

    blocks: list[SearchReplaceBlock]
    applications: list[BlockApplication]
    patch_content: str | None
    valid: bool
    errors: list[str]
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "valid": self.valid,
            "errors": self.errors,
            "blocks": [
                {"file_path": b.file_path, "search": b.search, "replace": b.replace}
                for b in self.blocks
            ],
            "applications": [
                {"file_path": a.block.file_path, "applied": a.applied, "error": a.error}
                for a in self.applications
            ],
            "patch_content": self.patch_content,
        }
