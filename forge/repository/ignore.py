"""Shared repository ignore rules."""

from __future__ import annotations

from pathlib import Path

IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "target",
        "build",
        "node_modules",
        "dist",
        ".idea",
        ".vscode",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    }
)


def normalize_root(root: Path | str | None = None) -> Path:
    """Return an absolute repository root path."""
    return Path(root or ".").expanduser().resolve()


def is_ignored_dir(name: str) -> bool:
    """Return whether a directory name should be skipped."""
    return name in IGNORED_DIR_NAMES


def is_ignored_path(path: Path, root: Path) -> bool:
    """Return whether a path is inside an ignored directory."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return any(part in IGNORED_DIR_NAMES for part in relative.parts)


def filter_dir_names(dir_names: list[str]) -> None:
    """Mutate an os.walk dir-name list to remove ignored directories."""
    dir_names[:] = sorted(name for name in dir_names if not is_ignored_dir(name))


def rg_ignore_globs() -> list[str]:
    """Return ripgrep glob arguments that mirror Forge ignore defaults."""
    globs: list[str] = []
    for name in sorted(IGNORED_DIR_NAMES):
        globs.extend(["--glob", f"!{name}/**"])
    return globs
