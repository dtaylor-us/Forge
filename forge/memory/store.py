"""Persistence layer for engineering memory items."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge.memory.models import MemoryItem, MemoryType

_MEMORY_DIR = ".forge/memory"
_INDEX_FILENAME = "index.json"
_TYPE_SUBDIRS = {
    MemoryType.plan: "plans",
    MemoryType.workset: "worksets",
    MemoryType.context_bundle: "context",
    MemoryType.adr: "architecture",
    MemoryType.architecture: "architecture",
    MemoryType.bug: "bugs",
    MemoryType.decision: "decisions",
    MemoryType.followup: "decisions",
}
SCHEMA_VERSION = 1


class MemoryStoreError(Exception):
    """Raised for store-level failures."""


def memory_dir(root: Path) -> Path:
    return root / _MEMORY_DIR


def index_path(root: Path) -> Path:
    return memory_dir(root) / _INDEX_FILENAME


def _item_dir(root: Path, item_type: MemoryType) -> Path:
    subdir = _TYPE_SUBDIRS.get(item_type, "decisions")
    return memory_dir(root) / subdir


def _item_path(root: Path, item: MemoryItem) -> Path:
    return _item_dir(root, item.type) / f"{item.id}.json"


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _ensure_dirs(root: Path) -> None:
    for subdir in set(_TYPE_SUBDIRS.values()):
        (memory_dir(root) / subdir).mkdir(parents=True, exist_ok=True)


def save_item(root: Path, item: MemoryItem) -> Path:
    """Persist a memory item and update the index. Returns the path written."""
    _ensure_dirs(root)
    path = _item_path(root, item)
    path.write_text(json.dumps(item.to_dict(), indent=2), encoding="utf-8")
    _update_index(root, item)
    return path


def load_item(root: Path, item_id: str) -> MemoryItem:
    """Load a memory item by id from the index. Raises MemoryStoreError if not found."""
    index = load_index(root)
    entry = next((e for e in index if e["id"] == item_id), None)
    if entry is None:
        raise MemoryStoreError(f"Memory item {item_id!r} not found.")
    item_type = MemoryType(entry["type"])
    path = _item_dir(root, item_type) / f"{item_id}.json"
    if not path.exists():
        raise MemoryStoreError(f"Memory item file missing for {item_id!r}.")
    return MemoryItem.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_items(root: Path) -> list[MemoryItem]:
    """Return all memory items from the index."""
    index = load_index(root)
    items: list[MemoryItem] = []
    for entry in index:
        try:
            items.append(load_item(root, entry["id"]))
        except MemoryStoreError:
            continue
    return items


def load_index(root: Path) -> list[dict[str, Any]]:
    """Load the flat index. Returns empty list if not found."""
    path = index_path(root)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("items", [])


def _save_index(root: Path, entries: list[dict[str, Any]]) -> None:
    path = index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": SCHEMA_VERSION, "items": entries}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _update_index(root: Path, item: MemoryItem) -> None:
    entries = load_index(root)
    entry = {
        "id": item.id,
        "type": item.type.value,
        "title": item.title,
        "created_at": item.created_at,
        "workset": item.workset,
        "tags": item.tags,
        "repository": item.repository,
        "summary": item.summary,
    }
    existing = next((e for e in entries if e["id"] == item.id), None)
    if existing is not None:
        entries = [e if e["id"] != item.id else entry for e in entries]
    else:
        entries.append(entry)
    _save_index(root, entries)


def rebuild_index(root: Path) -> int:
    """Scan all item files and rebuild the index from scratch. Returns count rebuilt."""
    _ensure_dirs(root)
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for subdir in set(_TYPE_SUBDIRS.values()):
        d = memory_dir(root) / subdir
        for path in sorted(d.glob("*.json")):
            try:
                item = MemoryItem.from_dict(json.loads(path.read_text(encoding="utf-8")))
                if item.id not in seen:
                    seen.add(item.id)
                    entries.append(
                        {
                            "id": item.id,
                            "type": item.type.value,
                            "title": item.title,
                            "created_at": item.created_at,
                            "workset": item.workset,
                            "tags": item.tags,
                            "repository": item.repository,
                            "summary": item.summary,
                        }
                    )
            except Exception:
                continue
    _save_index(root, entries)
    return len(entries)


def delete_item(root: Path, item_id: str) -> None:
    """Remove a memory item by id. Raises MemoryStoreError if not found."""
    item = load_item(root, item_id)
    path = _item_path(root, item)
    if path.exists():
        path.unlink()
    entries = [e for e in load_index(root) if e["id"] != item_id]
    _save_index(root, entries)
