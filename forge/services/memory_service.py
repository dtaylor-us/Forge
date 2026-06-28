"""Engineering memory application service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.memory.manager import MemoryManager
from forge.memory.models import MemoryType
from forge.memory.search import search_memory


def list_timeline(root: Path) -> list[dict[str, Any]]:
    """Return memory items sorted by created time descending."""
    return [item.to_dict() for item in MemoryManager.from_root(root).list()]


def get(root: Path, item_id: str) -> dict[str, Any]:
    """Return one memory item."""
    return MemoryManager.from_root(root).get(item_id).to_dict()


def search(root: Path, query: str, *, max_results: int = 10) -> dict[str, Any]:
    """Search memory deterministically."""
    results = search_memory(root, query, max_results=max_results)
    return {
        "query": query,
        "results": [
            {
                "item": result.item.to_dict(),
                "score": result.score,
                "reasons": [
                    {
                        "signal": reason.signal,
                        "detail": reason.detail,
                        "points": reason.points,
                    }
                    for reason in result.reasons
                ],
            }
            for result in results
        ],
    }


def add_item(
    root: Path,
    *,
    type: MemoryType,
    title: str,
    summary: str = "",
    workset: str = "",
    tags: list[str] | None = None,
    related_files: list[str] | None = None,
) -> dict[str, Any]:
    """Create a memory item."""
    item = MemoryManager.from_root(root).add(
        type=type,
        title=title,
        repository=str(root),
        workset=workset,
        tags=tags or [],
        summary=summary,
        related_files=related_files or [],
        related_worksets=[workset] if workset else [],
    )
    return item.to_dict()


def create_decision(root: Path, title: str, summary: str, workset: str = "") -> dict[str, Any]:
    """Create an engineering decision memory item."""
    return add_item(
        root,
        type=MemoryType.decision,
        title=title,
        summary=summary,
        workset=workset,
        tags=["decision"],
    )


def create_investigation(root: Path, title: str, summary: str, workset: str = "") -> dict[str, Any]:
    """Create a bug investigation memory item."""
    return add_item(
        root,
        type=MemoryType.bug,
        title=title,
        summary=summary,
        workset=workset,
        tags=["investigation"],
    )
