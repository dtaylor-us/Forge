"""High-level operations on the Engineering Memory store."""

from __future__ import annotations

import uuid
from pathlib import Path

from forge.memory.models import MemoryItem, MemoryType
from forge.memory.store import (
    delete_item,
    list_items,
    load_item,
    now_iso,
    rebuild_index,
    save_item,
)


class MemoryManager:
    """Provides CRUD and indexing operations for engineering memory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def add(
        self,
        *,
        type: MemoryType,
        title: str,
        repository: str = "",
        workset: str = "",
        tags: list[str] | None = None,
        summary: str = "",
        related_files: list[str] | None = None,
        related_plans: list[str] | None = None,
        related_worksets: list[str] | None = None,
        source_path: str = "",
        item_id: str | None = None,
    ) -> MemoryItem:
        """Create and persist a new memory item. Returns the saved item."""
        item = MemoryItem(
            id=item_id or str(uuid.uuid4())[:8],
            type=type,
            title=title,
            created_at=now_iso(),
            repository=repository,
            workset=workset,
            tags=tags or [],
            summary=summary,
            related_files=related_files or [],
            related_plans=related_plans or [],
            related_worksets=related_worksets or [],
            source_path=source_path,
        )
        save_item(self._root, item)
        return item

    def get(self, item_id: str) -> MemoryItem:
        """Retrieve a memory item by id. Raises MemoryStoreError if missing."""
        return load_item(self._root, item_id)

    def list(self) -> list[MemoryItem]:
        """Return all memory items sorted by created_at descending."""
        items = list_items(self._root)
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def delete(self, item_id: str) -> None:
        """Remove a memory item by id."""
        delete_item(self._root, item_id)

    def rebuild(self) -> int:
        """Rebuild the memory index from disk. Returns count of items indexed."""
        return rebuild_index(self._root)

    @staticmethod
    def from_root(root: Path) -> MemoryManager:
        return MemoryManager(root)
