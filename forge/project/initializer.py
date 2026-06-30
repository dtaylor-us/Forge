"""Initialize .forge/ project directory structure."""

from __future__ import annotations

from dataclasses import dataclass, field

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
    "verifications",
)

_GITIGNORE_HEADER = (
    "# Added by `forge init` — keep local Forge state and Python artifacts out of git.\n"
)
_GITIGNORE_ENTRIES = (
    ".forge/",
    "__pycache__/",
    "*.py[cod]",
)


@dataclass(frozen=True)
class InitResult:
    paths: ForgePaths
    already_existed: bool
    forced: bool
    gitignore_updated: bool = False
    gitignore_entries_added: list[str] = field(default_factory=list)


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

    gitignore_updated, gitignore_entries_added = _ensure_gitignore(resolved)

    return InitResult(
        paths=paths,
        already_existed=already_existed,
        forced=force,
        gitignore_updated=gitignore_updated,
        gitignore_entries_added=gitignore_entries_added,
    )


def _ensure_gitignore(resolved: ResolvedRoot) -> tuple[bool, list[str]]:
    """Ensure .forge/ and common Python artifacts are excluded from version control.

    Only applies when the root is a detected git repository. Appends any
    missing entries to an existing .gitignore, or creates a new one; never
    removes or reorders existing content.
    """
    if not resolved.git_detected:
        return False, []

    gitignore_path = resolved.root / ".gitignore"
    existing_lines: list[str] = []
    if gitignore_path.exists():
        try:
            existing_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False, []

    existing_set = {line.strip() for line in existing_lines}
    missing = [entry for entry in _GITIGNORE_ENTRIES if entry not in existing_set]
    if not missing:
        return False, []

    try:
        with gitignore_path.open("a", encoding="utf-8") as fh:
            if existing_lines and existing_lines[-1].strip() != "":
                fh.write("\n")
            fh.write(_GITIGNORE_HEADER)
            for entry in missing:
                fh.write(f"{entry}\n")
    except OSError:
        return False, []

    return True, missing
