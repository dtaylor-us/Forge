"""Workset candidate suggestion orchestration."""

from __future__ import annotations

from pathlib import Path

from forge.project.resolver import resolve_root
from forge.repository.files import list_relevant_files
from forge.worksets.candidate import WorksetCandidate, WorksetSuggestion
from forge.worksets.query import parse_query
from forge.worksets.ranking import assemble_workset
from forge.worksets.relationships import relationship_for_path, relationship_targets
from forge.worksets.scoring import (
    file_category,
    score_candidate,
)

_CONTENT_SCAN_EXTENSIONS = {
    ".py",
    ".java",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".kt",
    ".scala",
    ".cs",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".xml",
    ".properties",
    ".gradle",
    ".sql",
    ".sh",
}
_MIN_SCORE = 1

# Reading every matched file's content is the expensive part of scoring (disk I/O per
# file), so it is bounded by a budget rather than capped by truncating the file listing
# itself. Files that already carry filename/path/identifier signal always get their
# content read (it's how relationship/relevance gets confirmed and excerpted); files with
# no such signal only get read while budget remains, which is enough to catch
# content-only matches in small-to-medium repos without making huge monorepos pay to
# content-scan every file just to find nothing.
_CONTENT_SCAN_BUDGET = 1500


def suggest_candidates(
    query: str,
    root: Path | str | None = None,
    *,
    max_results: int = 20,
    include_tests: bool = False,
    workflow: str | None = None,
) -> WorksetSuggestion:
    """Return ranked workset candidates for a query using deterministic signals only."""
    root_path = resolve_root(override=root).root
    parsed_query = parse_query(query, include_tests=include_tests, workflow=workflow)
    tokens = parsed_query.tokens

    if not tokens:
        return WorksetSuggestion(query=query, tokens=[], candidates=[], root=root_path)

    # No truncation here: enumeration is cheap (no file reads), and a fixed cap applied
    # before scoring can silently drop the very file the query is looking for in a large
    # repository. See list_relevant_files()'s docstring.
    all_files = list_relevant_files(root_path, max_results=None)
    relationship_names = relationship_targets(parsed_query)
    candidates: list[WorksetCandidate] = []
    content_scan_budget = _CONTENT_SCAN_BUDGET

    for rel_path in all_files:
        category = file_category(rel_path)
        if category == "test" and not parsed_query.include_tests:
            continue

        relationship = relationship_for_path(rel_path, relationship_names)

        # Cheap pass: filename/path/identifier signal only, no disk I/O.
        cheap_candidate = score_candidate(rel_path, parsed_query, None, relationship=relationship)
        candidate = cheap_candidate
        if cheap_candidate.confidence > 0:
            content_lines = _read_content_lines(root_path / rel_path)
            if content_lines is not None:
                candidate = score_candidate(
                    rel_path, parsed_query, content_lines, relationship=relationship
                )
        elif content_scan_budget > 0:
            content_scan_budget -= 1
            content_lines = _read_content_lines(root_path / rel_path)
            if content_lines is not None:
                candidate = score_candidate(
                    rel_path, parsed_query, content_lines, relationship=relationship
                )

        if candidate.confidence >= _MIN_SCORE:
            candidates.append(candidate)

    assembled = assemble_workset(candidates, max_results=max_results)

    return WorksetSuggestion(
        query=query,
        tokens=tokens,
        candidates=assembled,
        root=root_path,
    )


def _read_content_lines(path: Path) -> list[str] | None:
    if path.suffix not in _CONTENT_SCAN_EXTENSIONS:
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.readlines()
    except OSError:
        return None
