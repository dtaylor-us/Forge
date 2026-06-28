"""Workset application service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.context.bundle import generate_bundle, save_bundle_markdown
from forge.context.render import render_markdown
from forge.project.paths import ForgePaths
from forge.worksets import suggest_candidates
from forge.worksets.manager import clear_workset, create_workset, get_workset, list_worksets
from forge.worksets.manager import refresh_workset as refresh_existing_workset


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
) -> dict[str, Any]:
    """Return deterministic workset suggestions."""
    suggestion = suggest_candidates(
        query,
        root,
        max_results=max_results,
        include_tests=include_tests,
    )
    return {
        "query": suggestion.query,
        "tokens": suggestion.tokens,
        "root": str(suggestion.root),
        "candidates": [
            {
                "path": candidate.path.as_posix(),
                "score": candidate.score,
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
) -> dict[str, Any]:
    """Create a persisted workset."""
    return create_workset(
        root,
        name,
        query,
        max_results=max_results,
        include_tests=include_tests,
        force=force,
    )


def detail(root: Path, name: str) -> dict[str, Any]:
    """Return a persisted workset."""
    return get_workset(root, name)


def refresh(root: Path, name: str) -> dict[str, Any]:
    """Refresh a persisted workset."""
    return refresh_existing_workset(root, name)


def delete(root: Path, name: str) -> dict[str, str]:
    """Delete a persisted workset."""
    clear_workset(root, name)
    return {"deleted": name}


def generate_context(
    root: Path,
    name: str,
    *,
    max_lines_per_file: int = 120,
    include_full: bool = False,
) -> dict[str, Any]:
    """Generate, save, and preview a context bundle for a workset."""
    paths = ForgePaths.from_root(root)
    bundle = generate_bundle(
        root,
        name,
        max_lines_per_file=max_lines_per_file,
        include_full=include_full,
    )
    rendered = render_markdown(bundle)
    ts = bundle.generated_at.replace(":", "-").replace("+", "").replace("Z", "")
    dest = paths.context_dir / f"{name}-{ts}.md"
    save_bundle_markdown(bundle, dest, rendered)
    return {
        "path": str(dest),
        "preview": rendered[:4000],
        "workset_name": bundle.workset_name,
        "file_count": len(bundle.files),
        "total_chars": bundle.total_chars,
        "total_tokens": bundle.total_tokens,
    }
