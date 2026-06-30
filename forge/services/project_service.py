"""Project application service."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from forge.project.initializer import initialize_project
from forge.project.metadata import load_metadata
from forge.project.paths import ForgePaths
from forge.project.resolver import ResolvedRoot, resolve_root
from forge.repository.detect import detect_repository

_PLAN_FILENAME_RE = re.compile(r"^(.*)-(\d{8}T\d{6})$")


def resolve_project_root(root: Path | str | None = None) -> ResolvedRoot:
    """Resolve a Forge repository root from an optional override."""
    return resolve_root(override=root)


def root_path(root: Path | str | None = None) -> dict[str, Any]:
    """Return resolved project root metadata."""
    resolved = resolve_project_root(root)
    return {"repo_root": str(resolved.root), "git_detected": resolved.git_detected}


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


def project_paths(root: Path) -> dict[str, str]:
    """Return important Forge paths for a project root."""
    return ForgePaths.from_root(resolve_root(override=root).root).to_dict()


def recent_plans(root: Path, *, limit: int = 5) -> list[dict[str, str]]:
    """Return recent saved plan artifacts."""
    paths = ForgePaths.from_root(root)
    if not paths.plans_dir.exists():
        return []
    plans = sorted(paths.plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": plan.name, "path": str(plan)} for plan in plans[:limit]]


def list_plans(root: Path, *, limit: int = 20) -> list[dict[str, str]]:
    """Return saved plan artifacts with metadata for the `forge plan-list` command.

    Each entry includes the workset and generated-at timestamp parsed from the
    filename (saved as ``<workset>-<timestamp>.md``), plus a short preview
    pulled from the first non-empty line of the plan content.
    """
    paths = ForgePaths.from_root(root)
    if not paths.plans_dir.exists():
        return []
    plans = sorted(paths.plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    results: list[dict[str, str]] = []
    for plan_path in plans[:limit]:
        workset, generated_at = _parse_plan_filename(plan_path.name)
        results.append(
            {
                "name": plan_path.name,
                "path": str(plan_path),
                "workset": workset,
                "generated_at": generated_at,
                "preview": _plan_preview(plan_path),
            }
        )
    return results


def _parse_plan_filename(filename: str) -> tuple[str, str]:
    """Parse `<workset>-<timestamp>.md` into (workset, ISO-8601 timestamp)."""
    stem = filename[:-3] if filename.endswith(".md") else filename
    match = _PLAN_FILENAME_RE.match(stem)
    if not match:
        return stem, "-"
    workset, ts = match.groups()
    try:
        return workset, datetime.strptime(ts, "%Y%m%dT%H%M%S").isoformat()
    except ValueError:
        return workset, "-"


def _plan_preview(plan_path: Path, *, max_len: int = 60) -> str:
    """Return a short preview from the first non-empty line of a saved plan."""
    try:
        for line in plan_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                return stripped[:max_len] + ("…" if len(stripped) > max_len else "")
    except OSError:
        pass
    return "-"


def initialize(root: Path, *, force: bool = False) -> dict[str, Any]:
    """Initialize Forge project metadata."""
    resolved = resolve_root(override=root)
    result = initialize_project(resolved, force=force)
    return {
        "already_existed": result.already_existed,
        "forced": result.forced,
        "paths": result.paths.to_dict(),
        "gitignore_updated": result.gitignore_updated,
        "gitignore_entries_added": result.gitignore_entries_added,
    }
