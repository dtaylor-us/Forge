"""Workset manager: create, add, remove, refresh worksets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.project.resolver import resolve_root
from forge.worksets import suggest_candidates
from forge.worksets.store import (
    WorksetStoreError,
    delete,
    exists,
    list_names,
    load,
    now_iso,
    save,
    validate_name,
)

SCHEMA_VERSION = 1


def _candidate_to_file_entry(candidate: Any, root: Path) -> dict[str, Any]:
    reasons = []
    for r in candidate.reasons:
        prefix = r.label.split(":", 1)[0]
        if prefix.endswith("Match"):
            signal = "match"
            detail = r.label.replace("Match:", "Match")
        elif ":" in r.label:
            signal, detail = r.label.split(":", 1)
        else:
            signal = "match"
            detail = r.label
        reasons.append({"signal": signal, "detail": detail, "points": r.score})
    return {
        "path": candidate.path.as_posix(),
        "score": candidate.score,
        "confidence": getattr(candidate, "confidence", 0),
        "importance": getattr(candidate, "importance", 0),
        "rank_group": getattr(candidate, "rank_group", "other"),
        "required": getattr(candidate, "required", False),
        "category": candidate.file_category,
        "reasons": reasons,
        "manual": False,
    }


def _validate_file_in_root(root: Path, file_path: Path) -> str:
    """Return relative POSIX path. Raises WorksetStoreError if outside root or missing."""
    abs_file = (root / file_path).resolve() if not file_path.is_absolute() else file_path.resolve()
    root_resolved = root.resolve()
    if not abs_file.is_relative_to(root_resolved):
        raise WorksetStoreError(f"File {file_path} is outside the workset root {root}.")
    if not abs_file.exists():
        raise WorksetStoreError(f"File {file_path} does not exist.")
    return abs_file.relative_to(root_resolved).as_posix()


def create_workset(
    root: Path | str | None,
    name: str,
    query: str,
    *,
    max_results: int = 20,
    include_tests: bool = False,
    force: bool = False,
    workflow: str | None = None,
) -> dict[str, Any]:
    """Create and persist a workset. Returns the saved data dict."""
    validate_name(name)
    root_path = resolve_root(override=root).root

    if exists(root_path, name) and not force:
        raise WorksetStoreError(f"Workset {name!r} already exists. Use --force to overwrite.")

    suggestion = suggest_candidates(
        query,
        root_path,
        max_results=max_results,
        include_tests=include_tests,
        workflow=workflow,
    )

    ts = now_iso()
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "query": query,
        "root": str(root_path),
        "created_at": ts,
        "updated_at": ts,
        "include_tests": include_tests,
        "max_results": max_results,
        "workflow": workflow,
        "files": [_candidate_to_file_entry(c, root_path) for c in suggestion.candidates],
    }
    save(root_path, data)
    return data


def add_file(root: Path | str | None, name: str, file_path: str | Path) -> dict[str, Any]:
    """Add a file to an existing workset. Returns updated data."""
    root_path = resolve_root(override=root).root
    data = load(root_path, name)

    rel_posix = _validate_file_in_root(root_path, Path(file_path))

    changed = False
    for entry in data["files"]:
        if entry["path"] == rel_posix:
            if not entry.get("manual"):
                entry["manual"] = True
                changed = True
            break
    else:
        data["files"].append(
            {
                "path": rel_posix,
                "score": 0,
                "category": "source",
                "reasons": [{"signal": "manual", "detail": "manually added", "points": 0}],
                "manual": True,
            }
        )
        changed = True
    if changed:
        data["updated_at"] = now_iso()
        save(root_path, data)
    return data


def remove_file(root: Path | str | None, name: str, file_path: str | Path) -> dict[str, Any]:
    """Remove a file from an existing workset. Returns updated data."""
    root_path = resolve_root(override=root).root
    data = load(root_path, name)

    target = Path(file_path).as_posix()
    before = len(data["files"])
    data["files"] = [f for f in data["files"] if f["path"] != target]
    if len(data["files"]) < before:
        data["updated_at"] = now_iso()
        save(root_path, data)
    return data


def refresh_workset(root: Path | str | None, name: str) -> dict[str, Any]:
    """Re-run the saved query and update the workset, preserving manual files."""
    root_path = resolve_root(override=root).root
    data = load(root_path, name)

    manual_paths = {f["path"] for f in data["files"] if f.get("manual")}

    suggestion = suggest_candidates(
        data["query"],
        root_path,
        max_results=data.get("max_results", 20),
        include_tests=data.get("include_tests", False),
        workflow=data.get("workflow"),
    )

    suggested_paths = {c.path.as_posix() for c in suggestion.candidates}
    surviving_manual = [
        f
        for f in data["files"]
        if f.get("manual") and f["path"] not in suggested_paths and (root_path / f["path"]).exists()
    ]

    suggested_entries = []
    for c in suggestion.candidates:
        entry = _candidate_to_file_entry(c, root_path)
        if entry["path"] in manual_paths:
            entry["manual"] = True
        suggested_entries.append(entry)

    data["files"] = suggested_entries + surviving_manual
    data["updated_at"] = now_iso()
    save(root_path, data)
    return data


def get_workset(root: Path | str | None, name: str) -> dict[str, Any]:
    root_path = resolve_root(override=root).root
    return load(root_path, name)


def list_worksets(root: Path | str | None) -> list[str]:
    root_path = resolve_root(override=root).root
    return list_names(root_path)


def clear_workset(root: Path | str | None, name: str) -> None:
    root_path = resolve_root(override=root).root
    delete(root_path, name)
