"""Patch storage and validation services."""

from __future__ import annotations

import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from forge.patches.models import Patch
from forge.project.paths import ForgePaths

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_MAX_CONTEXT_MISMATCHES_PER_HUNK = 5
_MAX_CONTEXT_MISMATCHES_TOTAL = 12
# Anchor-line realignment: lines whose content is too short or structurally trivial
# (single brackets, closing braces, blank lines) to serve as unique position anchors.
_ANCHOR_MIN_LEN = 8  # minimum stripped length
_ANCHOR_TRIVIAL_RE = re.compile(r"^\s*[\{\}\(\)\[\];,]?\s*$")


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


def apply_check_patch_content(root: Path, content: str) -> tuple[bool, str]:
    """Dry-run git apply for patch content and return (ok, error_message)."""
    from forge.git.service import GitService, GitServiceError

    git_svc = GitService(cwd=root)
    with tempfile.NamedTemporaryFile(
        suffix=".patch",
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(_ensure_trailing_newline(content))

    try:
        git_svc.apply_check(tmp_path)
        return True, ""
    except GitServiceError as exc:
        return False, str(exc)
    finally:
        with suppress(OSError):
            tmp_path.unlink()


@dataclass
class _Hunk:
    """The old-file side of a single diff hunk, as literal expected lines."""

    old_start: int
    old_lines: list[str] = field(default_factory=list)


def realign_patch_hunk_headers(root: Path, content: str) -> tuple[str, list[str]]:
    """Deterministically correct miscounted hunk starting positions.

    ``git apply --recount`` (used by ``GitService``) fixes a hunk header's
    line *counts* by recomputing them from the hunk body, but it cannot fix
    a wrong starting *position* the same way.  A model that miscounts an
    ``@@ -L,N +L,N @@`` header is just as likely to get *L* wrong as *N*:
    both come from "counting lines by eye", and a wrong *L* produces a
    context mismatch that ``--recount`` cannot recover.

    This walks each hunk's literal old-file lines (context + removed) and,
    when they do not match the file at the header's stated position, searches
    the real file for the unique contiguous location where that exact block
    occurs.  When exactly one match is found the hunk's old/new start lines
    are corrected by the same offset; line counts are left untouched so that
    ``git apply --recount`` can absorb any remaining count errors.

    Hunks with no old-file lines (pure insertions) and hunks whose block
    occurs zero or more than one time in the file are left untouched —
    deterministic realignment requires a unique anchor.

    Returns the (possibly corrected) patch text and a list of human-readable
    notes describing every correction that was applied.
    """
    lines = content.splitlines(keepends=False)
    out: list[str] = []
    notes: list[str] = []

    current_file: str | None = None
    actual_lines: list[str] | None = None
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        if line.startswith("diff --git "):
            current_file = None
            actual_lines = None
            out.append(line)
            i += 1
            continue

        if line.startswith("--- "):
            out.append(line)
            i += 1
            continue

        if line.startswith("+++ "):
            path = _strip_header_path(line[4:])
            current_file = path or None
            actual_lines = None
            if current_file:
                target = root / current_file
                if target.exists():
                    try:
                        actual_lines = target.read_text(encoding="utf-8").splitlines()
                    except (OSError, UnicodeDecodeError):
                        actual_lines = None
            out.append(line)
            i += 1
            continue

        header_match = _HUNK_HEADER_RE.match(line)
        if header_match and actual_lines is not None:
            old_start = int(header_match.group(1))
            new_start = int(header_match.group(3))

            # Collect the full hunk body (everything until the next section boundary).
            body_start = i + 1
            j = body_start
            old_block: list[str] = []
            while j < n and not (
                lines[j].startswith("@@")
                or lines[j].startswith("diff --git ")
                or lines[j].startswith("--- ")
                or lines[j].startswith("+++ ")
            ):
                body_line = lines[j]
                if body_line.startswith(" ") or (
                    body_line.startswith("-") and not body_line.startswith("---")
                ):
                    old_block.append(body_line[1:])
                elif body_line == "":
                    old_block.append("")
                j += 1
            hunk_body = lines[body_start:j]

            corrected_header = line
            if old_block and not _matches_at(actual_lines, old_start, old_block):
                matches = _find_block_matches(actual_lines, old_block)
                if len(matches) == 1:
                    new_old_start = matches[0] + 1  # convert 0-based to 1-based
                    delta = new_old_start - old_start
                    corrected_new_start = new_start + delta
                    candidate = _rewrite_hunk_header(line, new_old_start, corrected_new_start)
                    if candidate != line:
                        corrected_header = candidate
                        if current_file:
                            notes.append(
                                f"{current_file}: realigned hunk header from line "
                                f"{old_start} to {new_old_start} "
                                "(content matched uniquely at a different position)."
                            )
                else:
                    # Full-block match failed (0 or ambiguous matches). Fall back to
                    # anchor-line realignment: find distinctive lines from the old-block
                    # that each appear exactly once in the file and agree on the same
                    # offset. This catches the common case where the model's context is
                    # correct but the hunk starts a few lines too early or too late
                    # (e.g. because a recently-added parameter shifted the method body).
                    delta = _anchor_line_delta(actual_lines, old_block, old_start)
                    if delta is not None and delta != 0:
                        new_old_start = old_start + delta
                        corrected_new_start = new_start + delta
                        if new_old_start >= 1:
                            candidate = _rewrite_hunk_header(line, new_old_start, corrected_new_start)
                            if candidate != line:
                                corrected_header = candidate
                                if current_file:
                                    notes.append(
                                        f"{current_file}: realigned hunk header from line "
                                        f"{old_start} to {new_old_start} "
                                        "(anchor-line match: distinctive lines agreed on "
                                        f"offset {delta:+d})."
                                    )

            out.append(corrected_header)
            out.extend(hunk_body)
            i = j
            continue

        out.append(line)
        i += 1

    rebuilt = "\n".join(out)
    if content.endswith("\n") and not rebuilt.endswith("\n"):
        rebuilt += "\n"
    return rebuilt, notes


def _matches_at(actual_lines: list[str], start: int, block: list[str]) -> bool:
    """Return True when ``block`` matches ``actual_lines`` exactly at 1-based ``start``."""
    if start < 1:
        return False
    end = start - 1 + len(block)
    if end > len(actual_lines):
        return False
    return actual_lines[start - 1 : end] == block


def _find_block_matches(actual_lines: list[str], block: list[str]) -> list[int]:
    """Return 0-based start indices where ``block`` occurs contiguously in ``actual_lines``.

    Stops after the second match so the caller can detect ambiguity cheaply.
    """
    if not block:
        return []
    span = len(block)
    limit = len(actual_lines) - span + 1
    matches: list[int] = []
    for idx in range(max(0, limit)):
        if actual_lines[idx : idx + span] == block:
            matches.append(idx)
            if len(matches) > 1:
                break  # ambiguous — no further scanning needed
    return matches


def _anchor_line_delta(
    actual_lines: list[str], old_block: list[str], old_start: int
) -> int | None:
    """Infer a hunk-start correction delta from distinctive lines in the old-block.

    When the full old-block cannot be found in the file (zero or ambiguous matches),
    the model may still have the *content* right but the *position* wrong — for example
    because a recently-added method parameter pushed the body down by two lines.

    This function identifies "anchor lines" — non-trivial lines that appear exactly once
    in the file — and computes each one's implied offset (file_position − expected_position).
    If two or more anchors agree on the same delta it is returned; if exactly one
    anchor exists and no other delta is observed, that single vote is returned.
    Returns ``None`` when no reliable delta can be established.
    """
    votes: dict[int, int] = {}  # delta -> number of anchors that agree

    for block_idx, block_line in enumerate(old_block):
        stripped = block_line.strip()
        if len(stripped) < _ANCHOR_MIN_LEN or _ANCHOR_TRIVIAL_RE.match(block_line):
            continue

        # Find all positions in the file where this line occurs exactly.
        file_positions = [i for i, fl in enumerate(actual_lines) if fl == block_line]
        if len(file_positions) != 1:
            # Line missing from file or appears multiple times — not a reliable anchor.
            continue

        actual_idx = file_positions[0]  # 0-based
        expected_idx = old_start - 1 + block_idx  # 0-based position the patch declares
        delta = actual_idx - expected_idx
        votes[delta] = votes.get(delta, 0) + 1

    if not votes:
        return None

    # Return the delta with the most votes.  Require a strict majority when multiple
    # deltas were observed (conflicting anchors → unreliable), but accept a single
    # unanimous delta unconditionally.
    best_delta, best_votes = max(votes.items(), key=lambda kv: kv[1])
    if len(votes) == 1 or best_votes >= 2:
        return best_delta
    return None


def _rewrite_hunk_header(original: str, new_old_start: int, new_new_start: int) -> str:
    """Rewrite a hunk header's starting positions, preserving counts and any suffix."""
    match = _HUNK_HEADER_RE.match(original)
    if not match:
        return original
    old_count = match.group(2)
    new_count = match.group(4)
    old_part = f"-{new_old_start}" + (f",{old_count}" if old_count is not None else "")
    new_part = f"+{new_new_start}" + (f",{new_count}" if new_count is not None else "")
    suffix = original[match.end() :]
    return f"@@ {old_part} {new_part} @@{suffix}"


def verify_patch_context(root: Path, content: str) -> list[str]:
    """Compare each hunk's context/removed lines against the real file on disk.

    ``git apply --check`` already rejects a patch whose context does not
    match the working tree, but it only reports a single generic failure
    location per file. When a model hallucinates file content (e.g. from an
    excerpted or stale view of the file), the same wrong context tends to
    reappear across repair attempts because the model never sees exactly
    *which* lines were wrong.

    This walks each hunk directly against the file on disk and returns
    concrete, line-numbered mismatch descriptions ("patch expected X, file
    actually has Y"), intended to be fed into a repair prompt so the model
    can ground its next attempt in the real file content instead of
    repeating the same guess.

    This does not replace ``apply_check_patch_content`` as the pass/fail
    gate — it is a best-effort diagnostic aid only.
    """
    mismatches: list[str] = []
    current_file: str | None = None
    current_hunk: _Hunk | None = None
    actual_lines: list[str] | None = None
    file_missing = False

    def flush() -> None:
        nonlocal current_hunk
        if current_hunk is None:
            return
        if file_missing and current_file:
            mismatches.append(f"{current_file}: file does not exist on disk.")
        elif actual_lines is not None and current_file:
            mismatches.extend(_check_hunk_context(current_file, current_hunk, actual_lines))
        current_hunk = None

    for raw_line in content.splitlines():
        if raw_line.startswith("diff --git "):
            flush()
            current_file = None
            actual_lines = None
            file_missing = False
            continue

        if raw_line.startswith("--- "):
            continue

        if raw_line.startswith("+++ "):
            flush()
            path = _strip_header_path(raw_line[4:])
            current_file = path or None
            actual_lines = None
            file_missing = False
            if current_file:
                target = root / current_file
                if target.exists():
                    try:
                        actual_lines = target.read_text(encoding="utf-8").splitlines()
                    except (OSError, UnicodeDecodeError):
                        actual_lines = None
                else:
                    file_missing = True
            continue

        header_match = _HUNK_HEADER_RE.match(raw_line)
        if header_match:
            flush()
            current_hunk = _Hunk(old_start=int(header_match.group(1)))
            continue

        if current_hunk is None:
            continue

        if raw_line.startswith(" ") or (
            raw_line.startswith("-") and not raw_line.startswith("---")
        ):
            current_hunk.old_lines.append(raw_line[1:])
        elif raw_line == "":
            current_hunk.old_lines.append("")
        # "+" (added) lines and anything else contribute nothing to the old side.

        if len(mismatches) >= _MAX_CONTEXT_MISMATCHES_TOTAL:
            break

    flush()
    return mismatches[:_MAX_CONTEXT_MISMATCHES_TOTAL]


def _check_hunk_context(file_path: str, hunk: _Hunk, actual_lines: list[str]) -> list[str]:
    found: list[str] = []
    for offset, expected in enumerate(hunk.old_lines):
        line_no = hunk.old_start + offset
        actual = actual_lines[line_no - 1] if 1 <= line_no <= len(actual_lines) else None
        if actual is None:
            found.append(
                f"{file_path}:{line_no}: patch expects a line here ({expected!r}) "
                f"but the file only has {len(actual_lines)} lines."
            )
        elif actual != expected:
            found.append(
                f"{file_path}:{line_no}: patch context does not match the real file.\n"
                f"    patch expected:    {expected!r}\n"
                f"    file actually has: {actual!r}"
            )
        if len(found) >= _MAX_CONTEXT_MISMATCHES_PER_HUNK:
            break
    return found


def inspect_patch(path: Path) -> Patch:
    """Return metadata and validation for a patch file."""
    errors: list[str]
    affected_files: list[str]
    raw_content = ""
    try:
        raw_content = path.read_text(encoding="utf-8")
        valid, errors, affected_files = validate_patch_content(raw_content)
    except UnicodeDecodeError:
        valid = False
        errors = ["Patch file must be valid UTF-8 text."]
        affected_files = []
    except OSError as exc:
        valid = False
        errors = [f"Unable to read patch file: {exc}"]
        affected_files = []

    stat = path.stat()
    added, removed = count_diff_lines(raw_content if valid else "")

    return Patch(
        name=path.name,
        path=path,
        created_at=_timestamp(stat.st_ctime),
        size_bytes=stat.st_size,
        valid=valid,
        validation_errors=errors,
        affected_files=affected_files,
        added_lines=added,
        removed_lines=removed,
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
    elif _has_orphan_hunk(lines):
        errors.append("Patch contains a hunk marker '@@' without a preceding file header.")

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


def _has_orphan_hunk(lines: list[str]) -> bool:
    """Return True if any @@ hunk marker lacks a preceding file header."""
    has_header = False
    for line in lines:
        if line.startswith("diff --git ") or line.startswith("--- ") or line.startswith("+++ "):
            has_header = True
        elif line.startswith("@@") and not has_header:
            return True
    return False


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


def count_diff_lines(content: str) -> tuple[int, int]:
    """Count added and removed lines in a unified diff."""
    added = removed = 0
    for line in content.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _ensure_trailing_newline(content: str) -> str:
    return content if content.endswith("\n") else content + "\n"
