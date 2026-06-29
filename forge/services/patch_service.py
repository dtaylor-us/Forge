"""Patch application service for saved patch inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.patches import list_patches, read_patch, validate_patch_file


def list_all(root: Path) -> list[dict[str, Any]]:
    """Return metadata for saved patches."""
    return [patch.to_dict() for patch in list_patches(root)]


def show(root: Path, patch_name: str) -> dict[str, Any]:
    """Return saved patch metadata and content."""
    patch = validate_patch_file(root, patch_name)
    data = patch.to_dict()
    data["content"] = read_patch(root, patch_name)
    return data


def validate(root: Path, patch_name: str) -> dict[str, Any]:
    """Validate a saved patch by name or direct path."""
    return validate_patch_file(root, patch_name).to_dict()
