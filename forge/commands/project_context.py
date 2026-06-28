"""Project-context assembly for explicit explanation commands."""

from __future__ import annotations

import os
from pathlib import Path

EXCLUDED_TREE_NAMES = {".git", ".venv", "target", "build", "node_modules", "dist"}
CONTEXT_FILES = [
    "README.md",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "go.mod",
    "docs/development/DEVELOPMENT_LOG.md",
]


def build_project_explanation_prompt(root: Path) -> str:
    """Build a compact prompt describing the current project directory."""
    parts = [
        "Explain this software project from the provided local context.",
        "Cover what the project is, its structure, and likely next development steps.",
        "",
        f"Project root: {root}",
        "",
        "Compact tree:",
        _compact_tree(root),
    ]
    for relative_path in CONTEXT_FILES:
        path = root / relative_path
        if path.is_file():
            parts.extend(["", f"File: {relative_path}", "```", _read_text(path), "```"])
    return "\n".join(parts)


def _compact_tree(root: Path, max_entries: int = 200) -> str:
    lines = [root.name or str(root)]
    count = 0
    for current_root, dir_names, file_names in os.walk(root):
        dir_names[:] = sorted(name for name in dir_names if name not in EXCLUDED_TREE_NAMES)
        file_names = sorted(file_names)
        current_path = Path(current_root)
        if current_path != root:
            relative = current_path.relative_to(root)
            lines.append(f"{'  ' * len(relative.parts)}{current_path.name}/")
            count += 1
        for file_name in file_names:
            if count >= max_entries:
                lines.append("...")
                return "\n".join(lines)
            file_path = current_path / file_name
            relative = file_path.relative_to(root)
            lines.append(f"{'  ' * len(relative.parts)}{file_name}")
            count += 1
        if count >= max_entries:
            lines.append("...")
            return "\n".join(lines)
    return "\n".join(lines)


def _read_text(path: Path, max_chars: int = 20_000) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) <= max_chars:
        return content
    return f"{content[:max_chars]}\n...[truncated]"
