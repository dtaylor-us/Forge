"""Deterministic scoring for workset candidate files."""

from __future__ import annotations

import re
from pathlib import Path

from forge.repository.files import (
    CONFIG_EXTENSIONS,
    IMPORTANT_FILENAMES,
    SOURCE_EXTENSIONS,
    TEST_ROOT_PARTS,
)
from forge.worksets.candidate import WorksetCandidate

# Points assigned per signal
SCORE_EXACT_FILENAME = 20
SCORE_FILENAME_TOKEN = 10
SCORE_PATH_SEGMENT_TOKEN = 5
SCORE_CONTENT_MATCH = 8
SCORE_IMPORTANT_FILE = 6
SCORE_SOURCE_FILE = 3
SCORE_CONFIG_FILE = 2
SCORE_DOC_FILE = 2
SCORE_TEST_PAIR = 4

_STOP_TOKENS = frozenset({"the", "a", "an", "of", "in", "to", "for", "and", "or", "is"})
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")

TEST_QUERY_TERMS = frozenset(
    {"test", "tests", "spec", "specs", "fixture", "fixtures", "regression"}
)


def tokenize_query(query: str) -> list[str]:
    """Split a query into lowercase tokens, filtering stop words and short tokens."""
    raw = _TOKEN_RE.findall(query.lower())
    return [t for t in raw if len(t) >= 2 and t not in _STOP_TOKENS]


def is_test_query(tokens: list[str]) -> bool:
    """Return True when query tokens suggest a test-focused search."""
    return bool(TEST_QUERY_TERMS & set(tokens))


def file_category(path: Path) -> str:
    """Classify a file as source, test, config, doc, or other."""
    parts = set(path.parts)
    if TEST_ROOT_PARTS & parts or any(
        p.startswith("test") or p.endswith("_test") or p.startswith("spec")
        for p in path.stem.split("_")
    ):
        name = path.stem
        if name.startswith("test_") or name.endswith("_test"):
            return "test"
        if TEST_ROOT_PARTS & parts:
            return "test"
    if path.suffix in {".md", ".rst", ".txt"} or "docs" in path.parts:
        return "doc"
    if path.suffix in CONFIG_EXTENSIONS or path.name in IMPORTANT_FILENAMES:
        return "config"
    if path.suffix in SOURCE_EXTENSIONS:
        return "source"
    return "other"


def score_candidate(
    path: Path,
    tokens: list[str],
    content_lines: list[str] | None = None,
) -> WorksetCandidate:
    """Score a file path against query tokens and return a WorksetCandidate."""
    candidate = WorksetCandidate(path=path, score=0, file_category=file_category(path))

    stem_lower = path.stem.lower()
    name_lower = path.name.lower()
    parts_lower = [p.lower() for p in path.parts]

    # Exact filename stem match against full query rebuild
    query_joined = "".join(tokens)
    if query_joined and stem_lower == query_joined:
        candidate.add_reason("exact filename match", SCORE_EXACT_FILENAME)

    # Per-token filename and path matches
    matched_filename_tokens: list[str] = []
    matched_path_tokens: list[str] = []
    for token in tokens:
        if token in stem_lower or token in name_lower:
            matched_filename_tokens.append(token)
        elif any(token in part for part in parts_lower[:-1]):
            matched_path_tokens.append(token)

    if matched_filename_tokens:
        label = f"filename matched {', '.join(repr(t) for t in matched_filename_tokens)}"
        candidate.add_reason(label, SCORE_FILENAME_TOKEN * len(matched_filename_tokens))
    if matched_path_tokens:
        label = f"path matched {', '.join(repr(t) for t in matched_path_tokens)}"
        candidate.add_reason(label, SCORE_PATH_SEGMENT_TOKEN * len(matched_path_tokens))

    # Content matches
    if content_lines:
        matched_terms: set[str] = set()
        matched_snippets: list[str] = []
        for line in content_lines:
            line_lower = line.lower()
            for token in tokens:
                if token in line_lower:
                    matched_terms.add(token)
                    stripped = line.strip()
                    if stripped and stripped not in matched_snippets:
                        matched_snippets.append(stripped)
        if matched_terms:
            label = f"content matched {', '.join(repr(t) for t in sorted(matched_terms))}"
            candidate.add_reason(label, SCORE_CONTENT_MATCH * len(matched_terms))
            candidate.content_matches = matched_snippets[:3]

    # File-type bonuses
    if path.name in IMPORTANT_FILENAMES:
        candidate.add_reason("important project file", SCORE_IMPORTANT_FILE)
    if candidate.file_category == "source":
        candidate.add_reason("source file", SCORE_SOURCE_FILE)
    elif candidate.file_category == "config":
        candidate.add_reason("config file", SCORE_CONFIG_FILE)
    elif candidate.file_category == "doc":
        candidate.add_reason("documentation file", SCORE_DOC_FILE)

    return candidate
