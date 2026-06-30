"""Data models for the search/replace patch pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SearchReplaceErrorType = Literal[
    "not_found",
    "ambiguous",
    "file_missing",
    "read_error",
    "no_change",
]


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
    failure_detail: SearchReplaceFailureDetail | None = None


@dataclass(frozen=True)
class SearchReplaceFailureDetail:
    """Structured diagnostic for a failed SEARCH/REPLACE block."""

    file_path: str
    error_type: SearchReplaceErrorType
    search_preview: str
    nearest_match_excerpt: str | None = None
    match_count: int | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "file_path": self.file_path,
            "error_type": self.error_type,
            "search_preview": self.search_preview,
            "nearest_match_excerpt": self.nearest_match_excerpt,
            "match_count": self.match_count,
            "message": self.message,
        }


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
    failure_details: list[SearchReplaceFailureDetail] = field(default_factory=list)

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
                {
                    "file_path": a.block.file_path,
                    "applied": a.applied,
                    "error": a.error,
                    "failure_detail": (
                        a.failure_detail.to_dict() if a.failure_detail is not None else None
                    ),
                }
                for a in self.applications
            ],
            "failure_details": [detail.to_dict() for detail in self.failure_details],
            "patch_content": self.patch_content,
        }
