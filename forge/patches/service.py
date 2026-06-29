"""Patch storage and validation services."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from forge.patches.models import Patch
from forge.project.paths import ForgePaths


class PatchError(Exception):
    """Raised for patch lookup or read failures."""


def patch_dir(root: Path) -> Path:
    """Return the project-local patch directory."""
    return ForgePaths.from_root(root).patches_dir


def ensure_patch_dir(root: Path) -> Path:
    """Create and return .forge/patches under root."""
    directory = patch_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def invalid_patch_dir(root: Path) -> Path:
    """Return the project-local invalid patch response directory."""
    return patch_dir(root) / "invalid"


def ensure_invalid_patch_dir(root: Path) -> Path:
    """Create and return .forge/patches/invalid under root."""
    directory = invalid_patch_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_patch_content(root: Path, content: str, *, prefix: str = "implement") -> Patch:
    """Save valid patch content under .forge/patches and return metadata."""
    directory = ensure_patch_dir(root)
    path = _unique_artifact_path(directory, prefix, ".patch")
    path.write_text(_ensure_trailing_newline(content), encoding="utf-8")
    return inspect_patch(path)


def save_invalid_response(root: Path, content: str, *, prefix: str = "implement") -> Path:
    """Save invalid model output under .forge/patches/invalid."""
    directory = ensure_invalid_patch_dir(root)
    path = _unique_artifact_path(directory, prefix, ".txt")
    path.write_text(_ensure_trailing_newline(content), encoding="utf-8")
    return path


def list_patches(root: Path) -> list[Patch]:
    """Return metadata for saved patches under .forge/patches."""
    directory = ensure_patch_dir(root)
    return [
        inspect_patch(path)
        for path in sorted(directory.iterdir(), key=lambda p: p.name)
        if path.is_file()
    ]


def resolve_patch_path(root: Path, path_or_name: str | Path) -> Path:
    """Resolve a saved patch name or direct path to an existing file."""
    candidate = Path(path_or_name).expanduser()
    if candidate.exists() and candidate.is_file():
        return candidate

    saved = patch_dir(root) / str(path_or_name)
    if saved.exists() and saved.is_file():
        return saved

    raise PatchError(f"Patch {str(path_or_name)!r} not found.")


def read_patch(root: Path, path_or_name: str | Path) -> str:
    """Read patch content by saved name or direct path."""
    path = resolve_patch_path(root, path_or_name)
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PatchError(f"Unable to read patch {path}: {exc}") from exc


def validate_patch_file(root: Path, path_or_name: str | Path) -> Patch:
    """Validate a saved patch name or direct path."""
    path = resolve_patch_path(root, path_or_name)
    return inspect_patch(path)


def inspect_patch(path: Path) -> Patch:
    """Return metadata and validation for a patch file."""
    errors: list[str]
    affected_files: list[str]
    try:
        content = path.read_text(encoding="utf-8")
        valid, errors, affected_files = validate_patch_content(content)
    except UnicodeDecodeError:
        valid = False
        errors = ["Patch file must be valid UTF-8 text."]
        affected_files = []
    except OSError as exc:
        valid = False
        errors = [f"Unable to read patch file: {exc}"]
        affected_files = []

    stat = path.stat()
    return Patch(
        name=path.name,
        path=path,
        created_at=_timestamp(stat.st_ctime),
        size_bytes=stat.st_size,
        valid=valid,
        validation_errors=errors,
        affected_files=affected_files,
    )


def validate_patch_content(content: str) -> tuple[bool, list[str], list[str]]:
    """Conservatively validate raw unified diff content."""
    errors: list[str] = []
    if not content.strip():
        errors.append("Patch is empty.")
        return False, errors, []

    if "```" in content:
        errors.append("Patch must be raw diff content, not a Markdown fenced block.")

    lines = content.splitlines()
    first = _first_nonempty_line(lines)
    if not first or not (first.startswith("diff --git ") or first.startswith("--- ")):
        errors.append("Patch must begin with raw diff content, not prose or explanation.")

    has_git_diff = any(line.startswith("diff --git ") for line in lines)
    has_old_header = any(line.startswith("--- ") for line in lines)
    has_new_header = any(line.startswith("+++ ") for line in lines)
    if not (has_git_diff or (has_old_header and has_new_header)):
        errors.append("Patch must contain 'diff --git' or both '--- ' and '+++ ' headers.")

    if not any(line.startswith("@@") for line in lines):
        errors.append("Patch must contain at least one hunk marker beginning with '@@'.")

    return not errors, errors, extract_affected_files(content)


def extract_affected_files(content: str) -> list[str]:
    """Best-effort affected file extraction from common diff headers."""
    files: list[str] = []
    for line in content.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                _add_file(files, _strip_diff_prefix(parts[3]))
            continue

        if line.startswith(("+++ ", "--- ")):
            _add_file(files, _strip_header_path(line[4:]))

    return files


def _first_nonempty_line(lines: list[str]) -> str:
    for line in lines:
        if line.strip():
            return line
    return ""


def _strip_header_path(value: str) -> str:
    path = value.strip().split("\t", maxsplit=1)[0].split(" ", maxsplit=1)[0]
    return _strip_diff_prefix(path)


def _strip_diff_prefix(path: str) -> str:
    if path == "/dev/null":
        return ""
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _add_file(files: list[str], path: str) -> None:
    if path and path not in files:
        files.append(path)


def _timestamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat(timespec="seconds")


def _unique_artifact_path(directory: Path, prefix: str, suffix: str) -> Path:
    safe_prefix = _safe_artifact_prefix(prefix)
    stem = f"{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}-{safe_prefix}"
    candidate = directory / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def _safe_artifact_prefix(value: str) -> str:
    result = "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in value)
    result = "-".join(part for part in result.strip("-_").split("-") if part)
    return result[:60] or "implement"


def _ensure_trailing_newline(content: str) -> str:
    return content if content.endswith("\n") else content + "\n"
