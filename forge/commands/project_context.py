"""Project-context assembly for explicit explanation commands."""

from __future__ import annotations

import os
import tomllib
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


def build_guardrailed_ask_prompt(root: Path, user_prompt: str) -> str:
    """Build a compact prompt that anchors generic asks to the local Forge project."""
    identity = _project_identity(root)
    return "\n".join(
        [
            "You are answering a question about the local software project in this directory.",
            (
                "When the user says Forge, interpret it as this local project "
                "unless they explicitly name another product."
            ),
            "Do not assume Autodesk Forge, Minecraft Forge, or any other product named Forge.",
            "",
            f"Project root: {root}",
            f"Project identity: {identity}",
            "",
            "User question:",
            user_prompt,
        ]
    )


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


def _project_identity(root: Path) -> str:
    pyproject_identity = _pyproject_identity(root / "pyproject.toml")
    readme_summary = _readme_summary(root / "README.md")
    if pyproject_identity and readme_summary:
        return f"{pyproject_identity}; {readme_summary}"
    return pyproject_identity or readme_summary or root.name or str(root)


def _pyproject_identity(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        project = tomllib.loads(_read_text(path)).get("project", {})
    except tomllib.TOMLDecodeError:
        return ""
    name = project.get("name")
    description = project.get("description")
    if isinstance(name, str) and isinstance(description, str):
        return f"{name} - {description}"
    if isinstance(name, str):
        return name
    if isinstance(description, str):
        return description
    return ""


def _readme_summary(path: Path) -> str:
    if not path.is_file():
        return ""
    for line in _read_text(path, max_chars=4_000).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", ">", "[", "---")):
            return stripped.replace("**", "")
    return ""


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
