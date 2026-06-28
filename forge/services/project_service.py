"""Project application service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.project.initializer import initialize_project
from forge.project.metadata import load_metadata
from forge.project.paths import ForgePaths
from forge.project.resolver import ResolvedRoot, resolve_root
from forge.repository.detect import detect_repository


def resolve_project_root(root: Path | str | None = None) -> ResolvedRoot:
    """Resolve a Forge repository root from an optional override."""
    return resolve_root(override=root)


def project_info(root: Path) -> dict[str, Any]:
    """Return project metadata and Forge paths."""
    resolved = resolve_root(override=root)
    paths = ForgePaths.from_root(resolved.root)
    meta = load_metadata(paths.project_forge_dir)
    detection = detect_repository(resolved.root)
    detected = meta.get("detected", {}) if meta else {}
    if not detected:
        detected = {
            "languages": detection.languages,
            "build_systems": detection.build_systems,
            "frameworks": detection.frameworks,
            "package_managers": detection.package_managers,
        }
    return {
        "initialized": meta is not None,
        "git_detected": resolved.git_detected,
        "project_name": (
            meta.get("project_name", resolved.root.name) if meta else resolved.root.name
        ),
        "repo_root": str(resolved.root),
        "paths": paths.to_dict(),
        "metadata": meta,
        "detected": detected,
    }


def initialize(root: Path, *, force: bool = False) -> dict[str, Any]:
    """Initialize Forge project metadata."""
    resolved = resolve_root(override=root)
    result = initialize_project(resolved, force=force)
    return {
        "already_existed": result.already_existed,
        "forced": result.forced,
        "paths": result.paths.to_dict(),
    }
