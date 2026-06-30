"""Relevant repository file listing."""

from __future__ import annotations

import os
from pathlib import Path

from forge.repository.ignore import filter_dir_names, normalize_root

SOURCE_EXTENSIONS = {
    ".cs",
    ".css",
    ".go",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".md",
    ".py",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".ts",
    ".tsx",
}
CONFIG_EXTENSIONS = {".json", ".toml", ".yaml", ".yml", ".xml", ".gradle", ".properties"}
IMPORTANT_FILENAMES = {
    "Dockerfile",
    "Makefile",
    "README",
    "README.md",
    "pom.xml",
    "build.gradle",
    "settings.gradle",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "angular.json",
    "docker-compose.yml",
}
PREFERRED_PARTS = {"src", "test", "tests", "docs", "config", "k8s", "charts"}
SOURCE_ROOT_PARTS = {"src", "app", "forge", "lib"}
TEST_ROOT_PARTS = {"test", "tests"}


def list_relevant_files(
    root: Path | str | None = None,
    *,
    ext: str | None = None,
    max_results: int | None = 200,
) -> list[Path]:
    """List source, test, config, and documentation files in a repository.

    `max_results=None` returns every relevant file with no truncation. Callers that need
    a full, unbiased candidate pool (e.g. workset scoring) must pass `None` rather than a
    large fixed number: any fixed cap, applied via the global priority+path sort below
    *before* relevance is actually evaluated, can silently drop the very file a caller is
    looking for in a large repository, no matter how relevant it turns out to be.
    """
    root_path = normalize_root(root)
    extension = _normalize_extension(ext)
    results: list[Path] = []
    for current_root, dir_names, file_names in os.walk(root_path):
        filter_dir_names(dir_names)
        current_path = Path(current_root)
        for file_name in sorted(file_names):
            path = current_path / file_name
            if extension and path.suffix != extension:
                continue
            if extension or _is_relevant(path, root_path):
                results.append(path.relative_to(root_path))
    ordered = sorted(results, key=_file_priority)
    if max_results is None:
        return ordered
    return ordered[:max_results]


def _normalize_extension(ext: str | None) -> str | None:
    if not ext:
        return None
    return ext if ext.startswith(".") else f".{ext}"


def _is_relevant(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if path.name in IMPORTANT_FILENAMES:
        return True
    if path.suffix in SOURCE_EXTENSIONS | CONFIG_EXTENSIONS:
        return True
    return any(part in PREFERRED_PARTS for part in relative.parts)


def _file_priority(path: Path) -> tuple[int, str]:
    parts = set(path.parts)
    if SOURCE_ROOT_PARTS & parts:
        priority = 0
    elif TEST_ROOT_PARTS & parts:
        priority = 1
    elif "docs" in parts:
        priority = 2
    else:
        priority = 3
    return priority, str(path)
