"""Workset persistence: path resolution, JSON read/write, list, and delete."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_WORKSETS_DIR = ".forge/worksets"
SCHEMA_VERSION = 1


class WorksetStoreError(Exception):
    """Raised for store-level validation or I/O failures."""


def validate_name(name: str) -> None:
    """Raise WorksetStoreError if name is invalid."""
    if not name:
        raise WorksetStoreError("Workset name must not be empty.")
    if not _NAME_RE.match(name):
        raise WorksetStoreError(
            f"Invalid workset name {name!r}. " "Use only letters, digits, hyphens, and underscores."
        )


def worksets_dir(root: Path) -> Path:
    """Return the .forge/worksets directory under root."""
    return root / _WORKSETS_DIR


def workset_path(root: Path, name: str) -> Path:
    """Return the JSON file path for a named workset."""
    validate_name(name)
    return worksets_dir(root) / f"{name}.json"


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def save(root: Path, data: dict[str, Any]) -> Path:
    """Write workset data to disk. Returns the path written."""
    name = data["name"]
    validate_name(name)
    path = workset_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load(root: Path, name: str) -> dict[str, Any]:
    """Read workset JSON. Raises WorksetStoreError if not found."""
    path = workset_path(root, name)
    if not path.exists():
        raise WorksetStoreError(f"Workset {name!r} not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def list_names(root: Path) -> list[str]:
    """Return sorted workset names found under root."""
    d = worksets_dir(root)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json") if p.is_file())


def delete(root: Path, name: str) -> None:
    """Delete a workset file. Raises WorksetStoreError if not found."""
    path = workset_path(root, name)
    if not path.exists():
        raise WorksetStoreError(f"Workset {name!r} not found.")
    path.unlink()


def exists(root: Path, name: str) -> bool:
    """Return True if the workset exists."""
    try:
        return workset_path(root, name).exists()
    except WorksetStoreError:
        return False
