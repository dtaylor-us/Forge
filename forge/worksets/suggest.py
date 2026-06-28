"""Workset candidate suggestion orchestration."""

from __future__ import annotations

from pathlib import Path

from forge.repository.files import list_relevant_files
from forge.repository.ignore import normalize_root
from forge.worksets.candidate import WorksetCandidate, WorksetSuggestion
from forge.worksets.scoring import (
    file_category,
    is_test_query,
    score_candidate,
    tokenize_query,
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


def suggest_candidates(
    query: str,
    root: Path | str | None = None,
    *,
    max_results: int = 20,
    include_tests: bool = False,
) -> WorksetSuggestion:
    """Return ranked workset candidates for a query using deterministic signals only."""
    root_path = normalize_root(root)
    tokens = tokenize_query(query)

    if not tokens:
        return WorksetSuggestion(query=query, tokens=[], candidates=[], root=root_path)

    include_tests = include_tests or is_test_query(tokens)

    all_files = list_relevant_files(root_path, max_results=2000)
    candidates: list[WorksetCandidate] = []

    for rel_path in all_files:
        category = file_category(rel_path)
        if category == "test" and not include_tests:
            continue

        abs_path = root_path / rel_path
        content_lines = _read_content_lines(abs_path)
        candidate = score_candidate(rel_path, tokens, content_lines)

        if candidate.score >= _MIN_SCORE:
            candidates.append(candidate)

    candidates.sort(key=lambda c: (-c.score, str(c.path)))

    return WorksetSuggestion(
        query=query,
        tokens=tokens,
        candidates=candidates[:max_results],
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
