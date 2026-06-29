"""Git application service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.git.service import GitService, GitServiceError


def status(root: Path | None = None) -> dict[str, Any]:
    """Return git status for the given directory."""
    svc = GitService(root)
    result = svc.status()
    return result.to_dict()


def branch(root: Path | None = None) -> dict[str, Any]:
    """Return current branch name."""
    svc = GitService(root)
    if not svc.is_git_repository():
        return {"is_git_repository": False, "branch": None}
    try:
        return {"is_git_repository": True, "branch": svc.branch()}
    except GitServiceError as exc:
        return {"is_git_repository": True, "branch": None, "error": str(exc)}
