"""Metadata helpers for existing artifact formats."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge.artifacts.models import ArtifactType


def artifact_id(
    artifact_type: ArtifactType,
    relative_path: str,
    intrinsic_id: str | None = None,
) -> str:
    """Return a stable registry identifier."""
    if intrinsic_id:
        return f"{artifact_type.value}:{intrinsic_id}"
    digest = hashlib.sha256(f"{artifact_type.value}:{relative_path}".encode()).hexdigest()
    return f"{artifact_type.value}:{digest[:16]}"


def relative_to_root(path: Path, root: Path) -> str:
    """Return a POSIX relative path when possible."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def read_json(path: Path) -> dict[str, Any]:
    """Load JSON object metadata, returning an empty object on failure."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def file_created_at(path: Path) -> str | None:
    """Return filesystem creation time as ISO-8601 when available."""
    try:
        return datetime.fromtimestamp(path.stat().st_ctime, tz=UTC).isoformat(timespec="seconds")
    except OSError:
        return None


def file_updated_at(path: Path) -> str | None:
    """Return filesystem modification time as ISO-8601 when available."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")
    except OSError:
        return None


def first_markdown_heading(path: Path) -> str:
    """Return the first markdown heading text, if one exists."""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
    except OSError:
        return ""
    return ""
