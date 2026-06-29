"""Repository application service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.git.service import GitService
from forge.repository import (
    detect_repository,
    generate_tree,
    list_relevant_files,
    search_repository,
)


def detect(root: Path) -> dict[str, Any]:
    """Return repository detection metadata."""
    result = detect_repository(root)
    current_branch: str | None = None
    try:
        git_svc = GitService(cwd=root)
        if git_svc.is_git_repository():
            current_branch = git_svc.branch()
    except Exception:  # noqa: BLE001
        pass
    return {
        "root_path": str(result.root_path),
        "languages": result.languages,
        "build_systems": result.build_systems,
        "package_managers": result.package_managers,
        "frameworks": result.frameworks,
        "source_roots": [path.as_posix() for path in result.source_roots],
        "test_roots": [path.as_posix() for path in result.test_roots],
        "important_files": [path.as_posix() for path in result.important_files],
        "current_branch": current_branch,
    }


def tree(root: Path, *, max_depth: int = 3) -> dict[str, Any]:
    """Return a compact repository tree."""
    return {"lines": generate_tree(root, max_depth=max_depth)}


def search(
    root: Path,
    query: str,
    *,
    globs: list[str] | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    """Search repository text with deterministic repository search."""
    matches = (
        search_repository(query, root, globs=globs or [], max_results=max_results) if query else []
    )
    return {
        "query": query,
        "matches": [
            {
                "path": match.path.as_posix(),
                "line_number": match.line_number,
                "line": match.line,
            }
            for match in matches
        ],
    }


def files(
    root: Path,
    *,
    ext: str | None = None,
    max_results: int = 200,
) -> dict[str, Any]:
    """Return repository files selected by deterministic repository rules."""
    return {
        "files": [
            path.as_posix() for path in list_relevant_files(root, ext=ext, max_results=max_results)
        ]
    }
