"""Apply SEARCH/REPLACE blocks to repository files and produce a unified diff.

No files are written to disk.  Each block is applied in memory; the resulting
modified content is diffed against the original with :mod:`difflib` to produce
a git-compatible unified diff string that can be saved as a ``.patch`` file and
handled by the existing patch pipeline (validate → apply-check → verify).
"""

from __future__ import annotations

import difflib
from pathlib import Path

from forge.srp.models import (
    BlockApplication,
    SearchReplaceBlock,
    SearchReplaceFailureDetail,
    SearchReplaceResult,
)

# Number of context lines to include on each side of a change in the produced
# unified diff.  Three is the git default and what `git apply` expects.
_CONTEXT_LINES = 3


def apply_blocks(root: Path, blocks: list[SearchReplaceBlock]) -> SearchReplaceResult:
    """Apply *blocks* to files under *root* and return a unified diff.

    Blocks are applied in declaration order within each file.  A later block's
    SEARCH content is matched against the *already-modified* content so that
    multiple edits to the same file compose correctly.

    Failure modes (per block):
    - **Not found**: the SEARCH string does not occur in the (possibly already
      modified) file content.  The block is skipped and its error is recorded.
    - **Ambiguous**: the SEARCH string occurs more than once.  The model must
      add more surrounding context to disambiguate.
    - **File missing**: the file does not exist under *root*.

    The returned :class:`~forge.srp.models.SearchReplaceResult` has
    ``valid=True`` and a non-``None`` ``patch_content`` only when every block
    was applied successfully and at least one file was modified.
    """
    if not blocks:
        return SearchReplaceResult(
            blocks=[],
            applications=[],
            patch_content=None,
            valid=False,
            errors=["No SEARCH/REPLACE blocks found in model output."],
        )

    # Group blocks by file, preserving declaration order within each file.
    file_order: list[str] = []
    by_file: dict[str, list[SearchReplaceBlock]] = {}
    for block in blocks:
        if block.file_path not in by_file:
            file_order.append(block.file_path)
            by_file[block.file_path] = []
        by_file[block.file_path].append(block)

    applications: list[BlockApplication] = []
    diff_parts: list[str] = []
    errors: list[str] = []
    failure_details: list[SearchReplaceFailureDetail] = []
    all_ok = True

    for file_path in file_order:
        file_blocks = by_file[file_path]
        abs_path = root / file_path

        # --- read original ---------------------------------------------------
        if not abs_path.exists():
            # Treat as new-file creation if every block for this file has an
            # empty SEARCH string; otherwise report missing file.
            if all(b.search == "" for b in file_blocks):
                result, apps, errs = _create_new_file(file_path, file_blocks)
                applications.extend(apps)
                errors.extend(errs)
                if result is not None:
                    diff_parts.append(result)
                else:
                    all_ok = False
                continue
            err = f"{file_path}: file not found."
            for block in file_blocks:
                detail = _failure_detail(
                    file_path=file_path,
                    error_type="file_missing",
                    block=block,
                    message=err,
                )
                applications.append(
                    BlockApplication(
                        block=block,
                        applied=False,
                        error=err,
                        failure_detail=detail,
                    )
                )
                failure_details.append(detail)
            errors.append(err)
            all_ok = False
            continue

        try:
            original = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            err = f"{file_path}: could not read file — {exc}"
            for block in file_blocks:
                detail = _failure_detail(
                    file_path=file_path,
                    error_type="read_error",
                    block=block,
                    message=err,
                )
                applications.append(
                    BlockApplication(
                        block=block,
                        applied=False,
                        error=err,
                        failure_detail=detail,
                    )
                )
                failure_details.append(detail)
            errors.append(err)
            all_ok = False
            continue

        # --- apply blocks sequentially ---------------------------------------
        modified = original
        file_ok = True
        for block in file_blocks:
            modified, app, err = _apply_one(file_path, block, modified)
            applications.append(app)
            if err:
                errors.append(err)
                if app.failure_detail is not None:
                    failure_details.append(app.failure_detail)
                file_ok = False
                all_ok = False
                break  # stop applying further blocks to this file on first failure

        # --- generate diff ---------------------------------------------------
        if file_ok and modified != original:
            diff = _unified_diff(file_path, original, modified)
            if diff:
                diff_parts.append(diff)

    patch_content = "".join(diff_parts) if (all_ok and diff_parts) else None
    valid = all_ok and bool(patch_content)

    if all_ok and not diff_parts:
        errors.append("All blocks applied but no file content changed.")
        valid = False

    return SearchReplaceResult(
        blocks=blocks,
        applications=applications,
        patch_content=patch_content,
        valid=valid,
        errors=errors,
        failure_details=failure_details,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _apply_one(
    file_path: str,
    block: SearchReplaceBlock,
    content: str,
) -> tuple[str, BlockApplication, str | None]:
    """Apply a single block against ``content``.  Returns (new_content, app, error_or_None)."""
    search = block.search
    replace = block.replace

    # Fast-path: exact match.
    if search in content:
        count = content.count(search)
        if count > 1:
            err = (
                f"{file_path}: SEARCH content matches {count} locations — add more "
                "surrounding context to make it unique."
            )
            detail = _failure_detail(
                file_path=file_path,
                error_type="ambiguous",
                block=block,
                content=content,
                message=err,
                match_count=count,
            )
            return (
                content,
                BlockApplication(block=block, applied=False, error=err, failure_detail=detail),
                err,
            )
        if search == replace:
            err = (
                f"{file_path}: SEARCH and REPLACE content are identical; "
                "no file content changed."
            )
            detail = _failure_detail(
                file_path=file_path,
                error_type="no_change",
                block=block,
                content=content,
                message=err,
                match_count=1,
            )
            return (
                content,
                BlockApplication(block=block, applied=False, error=err, failure_detail=detail),
                err,
            )
        new_content = content.replace(search, replace, 1)
        return new_content, BlockApplication(block=block, applied=True), None

    # Fallback: normalise CRLF → LF and retry.
    norm_search = search.replace("\r\n", "\n")
    norm_content = content.replace("\r\n", "\n")
    if norm_search in norm_content:
        count = norm_content.count(norm_search)
        if count > 1:
            err = (
                f"{file_path}: SEARCH content matches {count} locations — add more "
                "surrounding context to make it unique."
            )
            detail = _failure_detail(
                file_path=file_path,
                error_type="ambiguous",
                block=block,
                content=norm_content,
                message=err,
                match_count=count,
            )
            return (
                content,
                BlockApplication(block=block, applied=False, error=err, failure_detail=detail),
                err,
            )
        if norm_search == replace.replace("\r\n", "\n"):
            err = (
                f"{file_path}: SEARCH and REPLACE content are identical; "
                "no file content changed."
            )
            detail = _failure_detail(
                file_path=file_path,
                error_type="no_change",
                block=block,
                content=norm_content,
                message=err,
                match_count=1,
            )
            return (
                content,
                BlockApplication(block=block, applied=False, error=err, failure_detail=detail),
                err,
            )
        new_content = norm_content.replace(norm_search, replace.replace("\r\n", "\n"), 1)
        return new_content, BlockApplication(block=block, applied=True), None

    err = (
        f"{file_path}: SEARCH content not found in file. "
        "Verify that the search string matches the file exactly, including all indentation."
    )
    detail = _failure_detail(
        file_path=file_path,
        error_type="not_found",
        block=block,
        content=content,
        message=err,
    )
    return (
        content,
        BlockApplication(block=block, applied=False, error=err, failure_detail=detail),
        err,
    )


def _create_new_file(
    file_path: str,
    blocks: list[SearchReplaceBlock],
) -> tuple[str | None, list[BlockApplication], list[str]]:
    """Produce a diff for a file that does not yet exist (pure creation)."""
    # Concatenate all replace strings in order.
    content = "\n".join(b.replace for b in blocks)
    if content and not content.endswith("\n"):
        content += "\n"
    apps = [BlockApplication(block=b, applied=True) for b in blocks]
    diff = _new_file_diff(file_path, content)
    return diff, apps, []


def _failure_detail(
    *,
    file_path: str,
    error_type: str,
    block: SearchReplaceBlock,
    message: str,
    content: str | None = None,
    match_count: int | None = None,
) -> SearchReplaceFailureDetail:
    return SearchReplaceFailureDetail(
        file_path=file_path,
        error_type=error_type,  # type: ignore[arg-type]
        search_preview=_preview(block.search),
        nearest_match_excerpt=_nearest_match_excerpt(content, block.search) if content else None,
        match_count=match_count,
        message=message,
    )


def _preview(text: str, limit: int = 180) -> str:
    compact = "\n".join(line for line in text.splitlines()[:6])
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _nearest_match_excerpt(content: str, search: str) -> str:
    """Return a deterministic diagnostic excerpt near the likely target."""
    file_lines = content.splitlines()
    if not file_lines:
        return ""
    needle = next((line.strip() for line in search.splitlines() if line.strip()), "")
    approx = 0
    if needle:
        for idx, line in enumerate(file_lines):
            if line.strip() == needle or needle in line.strip():
                approx = idx
                break
        else:
            needle_lower = needle.lower()
            for idx, line in enumerate(file_lines):
                if line.strip().lower() == needle_lower or needle_lower in line.strip().lower():
                    approx = idx
                    break
            else:
                approx = 0

    if approx == 0 and needle:
        end = min(40, len(file_lines))
        start = 0
    else:
        start = max(0, approx - 10)
        end = min(len(file_lines), approx + 11)

    snippet = []
    for idx in range(start, end):
        marker = ">>>" if idx == approx else "   "
        snippet.append(f"{idx + 1:>5}{marker}| {file_lines[idx]}")
    return "\n".join(snippet)


def _unified_diff(file_path: str, original: str, modified: str) -> str:
    """Produce a git-compatible unified diff between *original* and *modified*."""
    original_lines = _to_lines(original)
    modified_lines = _to_lines(modified)

    diff_iter = difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        n=_CONTEXT_LINES,
    )
    hunks = list(diff_iter)
    if not hunks:
        return ""
    return f"diff --git a/{file_path} b/{file_path}\n" + "".join(hunks)


def _new_file_diff(file_path: str, content: str) -> str:
    """Produce a unified diff for a brand-new file (no original)."""
    lines = _to_lines(content)
    diff_iter = difflib.unified_diff(
        [],
        lines,
        fromfile="/dev/null",
        tofile=f"b/{file_path}",
        n=_CONTEXT_LINES,
    )
    hunks = list(diff_iter)
    if not hunks:
        return ""
    return (
        f"diff --git a/{file_path} b/{file_path}\n"
        "new file mode 100644\n"
        + "".join(hunks)
    )


def _to_lines(text: str) -> list[str]:
    """Split text into lines, ensuring each ends with ``\\n``."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines
