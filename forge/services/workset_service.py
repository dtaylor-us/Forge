"""Workset application service."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from forge.context.bundle import generate_bundle, save_bundle_markdown
from forge.context.render import render_json, render_markdown
from forge.project.paths import ForgePaths
from forge.services import memory_service
from forge.worksets import suggest_candidates
from forge.worksets.manager import (
    add_file,
    clear_workset,
    create_workset,
    get_workset,
    list_worksets,
)
from forge.worksets.manager import (
    refresh_workset as refresh_existing_workset,
)
from forge.worksets.manager import (
    remove_file as remove_workset_file,
)


def list_all(root: Path) -> list[dict[str, Any]]:
    """Return persisted worksets with summary metadata."""
    items: list[dict[str, Any]] = []
    for name in list_worksets(root):
        try:
            data = get_workset(root, name)
        except Exception:
            items.append({"name": name, "unreadable": True})
            continue
        items.append(
            {
                "name": data.get("name", name),
                "query": data.get("query", ""),
                "file_count": len(data.get("files", [])),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
            }
        )
    return items


def suggest(
    root: Path,
    query: str,
    *,
    max_results: int = 20,
    include_tests: bool = False,
    workflow: str | None = None,
) -> dict[str, Any]:
    """Return deterministic workset suggestions."""
    suggestion = suggest_candidates(
        query,
        root,
        max_results=max_results,
        include_tests=include_tests,
        workflow=workflow,
    )
    return {
        "query": suggestion.query,
        "tokens": suggestion.tokens,
        "root": str(suggestion.root),
        "candidates": [
            {
                "path": candidate.path.as_posix(),
                "score": candidate.score,
                "confidence": candidate.confidence,
                "importance": candidate.importance,
                "rank_group": candidate.rank_group,
                "required": candidate.required,
                "file_category": candidate.file_category,
                "reasons": [
                    {"label": reason.label, "score": reason.score} for reason in candidate.reasons
                ],
                "content_matches": candidate.content_matches,
            }
            for candidate in suggestion.candidates
        ],
    }


def create(
    root: Path,
    name: str,
    query: str,
    *,
    max_results: int = 20,
    include_tests: bool = False,
    force: bool = False,
    workflow: str | None = None,
) -> dict[str, Any]:
    """Create a persisted workset."""
    return create_workset(
        root,
        name,
        query,
        max_results=max_results,
        include_tests=include_tests,
        force=force,
        workflow=workflow,
    )


def detail(root: Path, name: str) -> dict[str, Any]:
    """Return a persisted workset, including any linked memory entries.

    Decisions and investigations created with `--workset <name>` are
    otherwise disconnected from the workset at the CLI level (visible only
    via `forge memory timeline`/`forge memory search`). Attaching them here
    lets `forge workset show` surface relevant prior context inline.
    """
    data = get_workset(root, name)
    data["memory"] = memory_service.linked_to_workset(root, name)
    return data


def refresh(root: Path, name: str) -> dict[str, Any]:
    """Refresh a persisted workset."""
    return refresh_existing_workset(root, name)


def add(root: Path, name: str, file_path: str | Path) -> dict[str, Any]:
    """Add a file to a persisted workset."""
    return add_file(root, name, file_path)


def remove(root: Path, name: str, file_path: str | Path) -> dict[str, Any]:
    """Remove a file from a persisted workset."""
    return remove_workset_file(root, name, file_path)


def delete(root: Path, name: str) -> dict[str, str]:
    """Delete a persisted workset."""
    clear_workset(root, name)
    return {"deleted": name}


def _filename_timestamp(generated_at: str) -> str:
    """Return a filesystem-safe timestamp for context bundle filenames.

    Naively replacing ":" and "+" in an ISO-8601 string (e.g.
    "2026-06-29T14:20:24+00:00") stripped the "+" right before the offset
    digits, producing a malformed "...142024-0000-00" style suffix that read
    as a confusing extra date/time component. Parse the timestamp instead and
    reformat it cleanly, marking UTC with a trailing "Z".
    """
    try:
        dt = datetime.fromisoformat(generated_at)
    except ValueError:
        # Fall back to a sanitized version of the raw string rather than
        # raising, since this only affects a filename, not correctness.
        return "".join(ch if ch.isalnum() else "-" for ch in generated_at)

    if dt.tzinfo is None:
        suffix = ""
    elif dt.utcoffset() == timedelta(0):
        suffix = "Z"
    else:
        suffix = dt.strftime("%z")
    return dt.strftime("%Y%m%dT%H%M%S") + suffix


def generate_context(
    root: Path,
    name: str,
    *,
    max_lines_per_file: int = 60,
    include_full: bool = False,
    output_path: Path | None = None,
    output_json: bool = False,
    save: bool = True,
) -> dict[str, Any]:
    """Generate, save, and preview a context bundle for a workset."""
    paths = ForgePaths.from_root(root)
    bundle = generate_bundle(
        root,
        name,
        max_lines_per_file=max_lines_per_file,
        include_full=include_full,
    )
    rendered = render_json(bundle) if output_json else render_markdown(bundle)
    dest: Path | None = output_path
    if dest is None and save:
        ts = _filename_timestamp(bundle.generated_at)
        dest = paths.context_dir / f"{name}-{ts}.{'json' if output_json else 'md'}"
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if output_json:
            dest.write_text(rendered, encoding="utf-8")
        else:
            save_bundle_markdown(bundle, dest, rendered)
    return {
        "path": str(dest) if dest is not None else None,
        "content": rendered,
        "preview": rendered[:4000],
        "workset_name": bundle.workset_name,
        "file_count": len(bundle.files),
        "total_chars": bundle.total_chars,
        "total_tokens": bundle.total_tokens,
    }
