"""Repository application service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.repository import detect_repository, generate_tree, search_repository


def detect(root: Path) -> dict[str, Any]:
    """Return repository detection metadata."""
    result = detect_repository(root)
    return {
        "root_path": str(result.root_path),
        "languages": result.languages,
        "build_systems": result.build_systems,
        "package_managers": result.package_managers,
        "frameworks": result.frameworks,
        "source_roots": [path.as_posix() for path in result.source_roots],
        "test_roots": [path.as_posix() for path in result.test_roots],
        "important_files": [path.as_posix() for path in result.important_files],
    }


def tree(root: Path, *, max_depth: int = 3) -> dict[str, Any]:
    """Return a compact repository tree."""
    return {"lines": generate_tree(root, max_depth=max_depth)}


def search(root: Path, query: str, *, max_results: int = 100) -> dict[str, Any]:
    """Search repository text with deterministic repository search."""
    matches = search_repository(query, root, max_results=max_results) if query else []
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
