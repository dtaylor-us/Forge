"""Engineering memory application service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.memory.manager import MemoryManager
from forge.memory.models import MemoryType
from forge.memory.search import search_memory
from forge.memory.similarity import find_similar


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


def related(
    root: Path,
    query: str,
    *,
    workset: str = "",
    max_results: int = 5,
) -> dict[str, Any]:
    """Find memory items similar to the current context."""
    results = find_similar(root, query, workset=workset, max_results=max_results)
    return {
        "query": query,
        "workset": workset,
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


def linked_to_workset(root: Path, workset: str) -> list[dict[str, Any]]:
    """Return memory items linked to a workset, newest first.

    A memory item is considered linked if it was created with this workset
    as its primary `workset`, or if the workset appears in its
    `related_worksets` list.
    """
    if not workset:
        return []
    items = MemoryManager.from_root(root).list()
    linked = [
        item
        for item in items
        if item.workset == workset or workset in item.related_worksets
    ]
    return [item.to_dict() for item in linked]


def rebuild(root: Path) -> dict[str, int]:
    """Rebuild the memory index."""
    return {"count": MemoryManager.from_root(root).rebuild()}


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


def create_decision(
    root: Path,
    title: str,
    summary: str = "",
    workset: str = "",
    tags: list[str] | None = None,
    related_files: list[str] | None = None,
) -> dict[str, Any]:
    """Create an engineering decision memory item."""
    extra_tags = list(tags) if tags else []
    if "decision" not in extra_tags:
        extra_tags.insert(0, "decision")
    return add_item(
        root,
        type=MemoryType.decision,
        title=title,
        summary=summary,
        workset=workset,
        tags=extra_tags,
        related_files=related_files,
    )


def create_investigation(
    root: Path,
    title: str,
    summary: str = "",
    workset: str = "",
    tags: list[str] | None = None,
    related_files: list[str] | None = None,
) -> dict[str, Any]:
    """Create an engineering investigation memory item."""
    extra_tags = list(tags) if tags else []
    if "investigation" not in extra_tags:
        extra_tags.insert(0, "investigation")
    return add_item(
        root,
        type=MemoryType.investigation,
        title=title,
        summary=summary,
        workset=workset,
        tags=extra_tags,
        related_files=related_files,
    )
