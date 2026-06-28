"""Project metadata model: load, save, validate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge.version import __version__

SCHEMA_VERSION = 1
_META_FILE = "project.json"


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def metadata_path(project_forge_dir: Path) -> Path:
    return project_forge_dir / _META_FILE


def load_metadata(project_forge_dir: Path) -> dict[str, Any] | None:
    """Load project.json or return None if it does not exist."""
    path = metadata_path(project_forge_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_metadata(project_forge_dir: Path, data: dict[str, Any]) -> Path:
    """Write project.json and return the path."""
    path = metadata_path(project_forge_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def build_metadata(
    root: Path,
    project_name: str,
    detected: dict[str, list[str]] | None = None,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    ts = _now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "project_name": project_name,
        "root": str(root),
        "created_at": created_at or ts,
        "updated_at": ts,
        "forge_version": __version__,
        "detected": detected
        or {
            "languages": [],
            "build_systems": [],
            "frameworks": [],
            "package_managers": [],
        },
    }
