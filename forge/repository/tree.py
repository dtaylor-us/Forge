"""Compact repository tree generation."""

from __future__ import annotations

from pathlib import Path

from forge.repository.ignore import filter_dir_names, normalize_root


def generate_tree(root: Path | str | None = None, max_depth: int = 3) -> list[str]:
    """Generate a compact, deterministic repository tree."""
    root_path = normalize_root(root)
    lines = [f"[D] {root_path.name or root_path}"]
    if max_depth < 1 or not root_path.exists():
        return lines
    _append_children(root_path, root_path, lines, max_depth=max_depth, depth=1)
    return lines


def _append_children(
    current: Path,
    root: Path,
    lines: list[str],
    *,
    max_depth: int,
    depth: int,
) -> None:
    if depth > max_depth:
        return
    try:
        dir_names = [path.name for path in current.iterdir() if path.is_dir()]
        file_paths = [path for path in current.iterdir() if path.is_file()]
    except OSError:
        return

    filter_dir_names(dir_names)
    directories = [current / name for name in dir_names]
    files = sorted(file_paths, key=lambda path: path.name.lower())
    entries = [(path, True) for path in directories] + [(path, False) for path in files]

    for path, is_dir in entries:
        relative = path.relative_to(root)
        indent = "  " * len(relative.parts)
        marker = "[D]" if is_dir else "[F]"
        suffix = "/" if is_dir else ""
        lines.append(f"{indent}{marker} {path.name}{suffix}")
        if is_dir:
            _append_children(path, root, lines, max_depth=max_depth, depth=depth + 1)
