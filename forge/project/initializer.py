"""Initialize .forge/ project directory structure."""

from __future__ import annotations

from dataclasses import dataclass

from forge.project.metadata import build_metadata, load_metadata, metadata_path, save_metadata
from forge.project.paths import ForgePaths
from forge.project.resolver import ResolvedRoot
from forge.repository.detect import detect_repository

_SUBDIRS = (
    "worksets",
    "summaries",
    "context",
    "architecture",
    "sessions",
    "cache",
    "plans",
    "memory",
    "patches",
)


@dataclass(frozen=True)
class InitResult:
    paths: ForgePaths
    already_existed: bool
    forced: bool


def initialize_project(resolved: ResolvedRoot, *, force: bool = False) -> InitResult:
    """Create .forge/ structure and project.json under the resolved root.

    Returns InitResult indicating whether the directory already existed.
    Raises FileExistsError if project.json exists and force is False.
    """
    paths = ForgePaths.from_root(resolved.root)
    meta_path = metadata_path(paths.project_forge_dir)
    already_existed = meta_path.exists()

    if already_existed and not force:
        raise FileExistsError(
            f"Forge project already initialized at {paths.project_forge_dir}. "
            "Use --force to reinitialize."
        )

    # Create all subdirectories.
    for subdir in _SUBDIRS:
        (paths.project_forge_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Detect repository characteristics for detected section.
    detection = detect_repository(resolved.root)
    detected = {
        "languages": detection.languages,
        "build_systems": detection.build_systems,
        "frameworks": detection.frameworks,
        "package_managers": detection.package_managers,
    }

    # Preserve created_at on force-reinit so history is not erased.
    created_at = None
    if already_existed and force:
        existing = load_metadata(paths.project_forge_dir)
        if existing:
            created_at = existing.get("created_at")

    project_name = resolved.root.name
    data = build_metadata(resolved.root, project_name, detected, created_at=created_at)
    save_metadata(paths.project_forge_dir, data)

    return InitResult(paths=paths, already_existed=already_existed, forced=force)
