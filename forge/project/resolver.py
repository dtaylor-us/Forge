"""Repository root resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResolvedRoot:
    """Result of resolving the repository root."""

    root: Path
    git_detected: bool


def resolve_root(
    start: Path | str | None = None,
    *,
    override: Path | str | None = None,
) -> ResolvedRoot:
    """Resolve the repository root.

    Resolution order:
    1. If *override* is provided, use that path directly.
    2. Otherwise walk upward from *start* (or cwd) looking for a .git directory.
    3. If no .git is found, return *start* with git_detected=False.
    """
    if override is not None:
        path = Path(override).expanduser().resolve()
        git_detected = (path / ".git").exists()
        return ResolvedRoot(root=path, git_detected=git_detected)

    base = Path(start or ".").expanduser().resolve()
    current = base
    while True:
        if (current / ".git").exists():
            return ResolvedRoot(root=current, git_detected=True)
        parent = current.parent
        if parent == current:
            break
        current = parent

    return ResolvedRoot(root=base, git_detected=False)
