"""Repository search backed by ripgrep with a Python fallback."""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from forge.repository.ignore import filter_dir_names, normalize_root, rg_ignore_globs


@dataclass(frozen=True)
class GrepMatch:
    """A repository text search match."""

    path: Path
    line_number: int
    line: str


def search_repository(
    pattern: str,
    root: Path | str | None = None,
    *,
    globs: list[str] | None = None,
    max_results: int = 100,
) -> list[GrepMatch]:
    """Search repository files using ripgrep when available."""
    root_path = normalize_root(root)
    rg = shutil.which("rg")
    if rg:
        return _search_with_rg(rg, pattern, root_path, globs or [], max_results)
    return _search_with_python(pattern, root_path, globs or [], max_results)


def _search_with_rg(
    rg: str,
    pattern: str,
    root: Path,
    globs: list[str],
    max_results: int,
) -> list[GrepMatch]:
    command = [
        rg,
        "--line-number",
        "--no-heading",
        "--color",
        "never",
        *rg_ignore_globs(),
    ]
    for glob in globs:
        command.extend(["--glob", glob])
    command.extend(["--", pattern, str(root)])
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode not in {0, 1}:
        return []
    matches: list[GrepMatch] = []
    for line in completed.stdout.splitlines():
        match = _parse_rg_line(line, root)
        if match:
            matches.append(match)
        if len(matches) >= max_results:
            break
    return matches


def _parse_rg_line(line: str, root: Path) -> GrepMatch | None:
    parts = line.split(":", 2)
    if len(parts) != 3:
        return None
    path_text, line_number_text, matched_line = parts
    try:
        line_number = int(line_number_text)
    except ValueError:
        return None
    path = Path(path_text)
    with suppress(ValueError):
        path = path.relative_to(root)
    return GrepMatch(path=path, line_number=line_number, line=matched_line)


def _search_with_python(
    pattern: str,
    root: Path,
    globs: list[str],
    max_results: int,
) -> list[GrepMatch]:
    matches: list[GrepMatch] = []
    for current_root, dir_names, file_names in os.walk(root):
        filter_dir_names(dir_names)
        current_path = Path(current_root)
        for file_name in sorted(file_names):
            path = current_path / file_name
            relative = path.relative_to(root)
            if globs and not _matches_any_glob(relative, globs):
                continue
            for line_number, line in _iter_text_lines(path):
                if pattern in line:
                    matches.append(GrepMatch(relative, line_number, line.rstrip("\n")))
                    if len(matches) >= max_results:
                        return matches
    return matches


def _matches_any_glob(path: Path, globs: list[str]) -> bool:
    path_text = path.as_posix()
    return any(
        fnmatch.fnmatch(path_text, glob) or fnmatch.fnmatch(path.name, glob) for glob in globs
    )


def _iter_text_lines(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as file:
            yield from enumerate(file, start=1)
    except OSError:
        return
