"""Deterministic scoring for workset candidate files."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from forge.repository.files import (
    CONFIG_EXTENSIONS,
    IMPORTANT_FILENAMES,
    SOURCE_EXTENSIONS,
    TEST_ROOT_PARTS,
)
from forge.worksets.candidate import WorksetCandidate
from forge.worksets.identifiers import is_test_identifier, normalize_identifier, split_identifier
from forge.worksets.query import MAX_TERM_WEIGHT, SearchTerm, WorksetQuery, parse_query

# Confidence dominates ranking.
SCORE_EXACT_IDENTIFIER = 80
SCORE_EXACT_FILENAME = 65
SCORE_RELATIONSHIP = 55
SCORE_FILENAME_TERM = 14
SCORE_PATH_TERM = 8
SCORE_CONTENT_MATCH = 6
SCORE_TEST_MATCH = 10

# Importance is intentionally smaller than direct relevance.
IMPORTANCE_SOURCE = 8
IMPORTANCE_TEST = 7
IMPORTANCE_CONFIG = 4
IMPORTANCE_DOC = 3
IMPORTANCE_INFRASTRUCTURE = 2


def tokenize_query(query: str) -> list[str]:
    """Return parsed query terms for backward-compatible callers."""
    return parse_query(query).tokens


def is_test_query(tokens: list[str] | str) -> bool:
    """Return True when query text or identifiers imply test-oriented work."""
    if isinstance(tokens, str):
        return parse_query(tokens).include_tests
    return parse_query(" ".join(tokens)).include_tests


def file_category(path: Path) -> str:
    """Classify a file as source, test, config, doc, or other."""
    parts = set(path.parts)
    stem = path.stem
    stem_parts = stem.split("_")
    if (
        TEST_ROOT_PARTS & parts
        or any(
            p.startswith("test") or p.endswith("_test") or p.startswith("spec")
            for p in stem_parts
        )
        or is_test_identifier(stem)
    ):
        return "test"
    if path.suffix in {".md", ".rst", ".txt"} or "docs" in path.parts:
        return "doc"
    if path.suffix in CONFIG_EXTENSIONS or path.name in IMPORTANT_FILENAMES:
        return "config"
    if path.suffix in SOURCE_EXTENSIONS:
        return "source"
    return "other"


def is_infrastructure_file(path: Path) -> bool:
    """Return whether a file is project infrastructure rather than implementation."""
    return path.name in IMPORTANT_FILENAMES or file_category(path) in {"config", "doc"}


def score_candidate(
    path: Path,
    query_or_tokens: WorksetQuery | Sequence[str],
    content_lines: list[str] | None = None,
    *,
    relationship: str | None = None,
) -> WorksetCandidate:
    """Score a file path against a parsed query and return an explainable candidate."""
    query = _coerce_query(query_or_tokens)
    candidate = WorksetCandidate(path=path, score=0, file_category=file_category(path))

    stem_normalized = normalize_identifier(path.stem)
    name_lower = path.name.lower()
    # Split on the *original*-case filename/path segments so CamelCase boundaries
    # (e.g. "SessionController" -> {"session", "controller"}) survive; lowercasing first
    # would collapse them into one opaque token and defeat boundary-aware matching below.
    stem_parts = {part.lower() for part in split_identifier(path.stem)}
    path_parts_lower = [part.lower() for part in path.parts[:-1]]
    path_parts_tokens = {
        part.lower() for segment in path.parts[:-1] for part in split_identifier(segment)
    }
    term_values = query.search_terms

    exact_identifier = _exact_identifier_match(stem_normalized, query.identifiers)
    if exact_identifier:
        _add_confidence(
            candidate,
            "Primary Match: exact identifier match",
            SCORE_EXACT_IDENTIFIER,
        )

    subject_normalized = normalize_identifier(query.subject)
    if subject_normalized and stem_normalized == subject_normalized and not exact_identifier:
        _add_confidence(candidate, "Primary Match: exact filename match", SCORE_EXACT_FILENAME)

    if relationship:
        _add_confidence(
            candidate,
            f"Relationship: related implementation file ({relationship})",
            SCORE_RELATIONSHIP,
        )

    filename_terms = _matched_terms(name_lower, stem_normalized, stem_parts, term_values)
    if filename_terms:
        label = "Identifier Match: filename matched " + ", ".join(
            repr(t.value.lower()) for t in filename_terms
        )
        points = sum(_term_points(SCORE_FILENAME_TERM, t) for t in filename_terms)
        _add_confidence(candidate, label, points)

    path_terms = _matched_path_terms(path_parts_lower, path_parts_tokens, term_values)
    if path_terms:
        label = "Path Match: path matched " + ", ".join(repr(t.value.lower()) for t in path_terms)
        points = sum(_term_points(SCORE_PATH_TERM, t) for t in path_terms)
        _add_confidence(candidate, label, points)

    if content_lines:
        _score_content(candidate, content_lines, term_values)

    if candidate.file_category == "test" and query.include_tests:
        _add_confidence(candidate, "Test Match: test file included for task", SCORE_TEST_MATCH)

    _add_importance(candidate, path)
    candidate.score = candidate.confidence * 10 + candidate.importance
    candidate.rank_group = _rank_group(candidate)
    return candidate


def _coerce_query(query_or_tokens: WorksetQuery | Sequence[str]) -> WorksetQuery:
    if isinstance(query_or_tokens, WorksetQuery):
        return query_or_tokens
    return parse_query(" ".join(query_or_tokens))


def _exact_identifier_match(stem_normalized: str, identifiers: list[str]) -> str:
    for identifier in identifiers:
        if stem_normalized == normalize_identifier(identifier):
            return identifier
    return ""


# Below this length, a raw substring match is too likely to be a coincidental hit inside
# an unrelated word (e.g. "api" inside "capitalize", "test" inside "latest") rather than a
# genuine reference, so short terms must match a whole identifier/path segment or a
# camelCase/snake_case-aware part instead of an arbitrary substring.
_MIN_SUBSTRING_TERM_LENGTH = 6


def _term_points(base: int, term: SearchTerm) -> int:
    """Scale a base score by how distinctive the matched term is."""
    return max(1, round(base * term.weight / MAX_TERM_WEIGHT))


def _content_tokens(line: str) -> set[str]:
    """Tokenize a content line into whole words and their camelCase/snake_case parts.

    Splitting must happen on the original-case line; lowercasing first destroys the
    CamelCase boundaries that split_identifier() relies on.
    """
    tokens: set[str] = set()
    for raw in _WORD_RE.findall(line):
        tokens.add(raw.lower())
        for part in split_identifier(raw):
            tokens.add(part.lower())
    return tokens


_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _matched_terms(
    name_lower: str,
    stem_normalized: str,
    stem_parts: set[str],
    terms: Sequence[SearchTerm],
) -> list[SearchTerm]:
    matches: list[SearchTerm] = []
    seen: set[str] = set()
    for term in terms:
        value_lower = term.value.lower()
        if value_lower in seen or len(value_lower) < 2:
            continue
        value_normalized = normalize_identifier(term.value)
        matched = (
            (value_normalized and value_normalized == stem_normalized)
            or value_lower in stem_parts
            or (
                len(value_normalized) >= _MIN_SUBSTRING_TERM_LENGTH
                and value_normalized in stem_normalized
            )
            or (len(value_lower) >= _MIN_SUBSTRING_TERM_LENGTH and value_lower in name_lower)
        )
        if matched:
            matches.append(term)
            seen.add(value_lower)
    return matches


def _matched_path_terms(
    path_parts_lower: list[str],
    path_parts_tokens: set[str],
    terms: Sequence[SearchTerm],
) -> list[SearchTerm]:
    matches: list[SearchTerm] = []
    seen: set[str] = set()
    for term in terms:
        value_lower = term.value.lower()
        if value_lower in seen or len(value_lower) < 2:
            continue
        matched = value_lower in path_parts_tokens or (
            len(value_lower) >= _MIN_SUBSTRING_TERM_LENGTH
            and any(value_lower in part for part in path_parts_lower)
        )
        if matched:
            matches.append(term)
            seen.add(value_lower)
    return matches


def _score_content(
    candidate: WorksetCandidate,
    content_lines: list[str],
    terms: Sequence[SearchTerm],
) -> None:
    pending = {term.value.lower(): term for term in terms if len(term.value) >= 2}
    matched: dict[str, SearchTerm] = {}
    matched_snippets: list[str] = []
    for line in content_lines:
        if not pending:
            break
        line_lower = line.lower()
        line_tokens: set[str] | None = None
        for value, term in list(pending.items()):
            is_match = False
            if len(value) >= _MIN_SUBSTRING_TERM_LENGTH and value in line_lower:
                is_match = True
            else:
                if line_tokens is None:
                    line_tokens = _content_tokens(line)
                is_match = value in line_tokens
            if is_match:
                matched[value] = term
                del pending[value]
                stripped = line.strip()
                if stripped and stripped not in matched_snippets:
                    matched_snippets.append(stripped)
    if matched:
        label = "Content Match: content matched " + ", ".join(repr(v) for v in sorted(matched))
        points = sum(_term_points(SCORE_CONTENT_MATCH, term) for term in matched.values())
        _add_confidence(candidate, label, points)
        candidate.content_matches = matched_snippets[:3]


def _add_confidence(candidate: WorksetCandidate, label: str, points: int) -> None:
    candidate.confidence += points
    candidate.add_reason(label, points)


def _add_importance(candidate: WorksetCandidate, path: Path) -> None:
    if candidate.file_category == "source":
        candidate.importance += IMPORTANCE_SOURCE
        candidate.add_reason("Importance: source file", IMPORTANCE_SOURCE)
    elif candidate.file_category == "test":
        candidate.importance += IMPORTANCE_TEST
        candidate.add_reason("Importance: test file", IMPORTANCE_TEST)
    elif candidate.file_category == "config":
        candidate.importance += IMPORTANCE_CONFIG
        label = "Infrastructure: project configuration"
        if path.name in IMPORTANT_FILENAMES:
            label = "Infrastructure: important project file"
        candidate.add_reason(label, IMPORTANCE_CONFIG)
    elif candidate.file_category == "doc":
        candidate.importance += IMPORTANCE_DOC
        candidate.add_reason("Documentation: documentation file", IMPORTANCE_DOC)
    elif path.name in IMPORTANT_FILENAMES:
        candidate.importance += IMPORTANCE_INFRASTRUCTURE
        candidate.add_reason("Infrastructure: important project file", IMPORTANCE_INFRASTRUCTURE)


def _rank_group(candidate: WorksetCandidate) -> str:
    reason_labels = [reason.label for reason in candidate.reasons]
    if (
        any(label.startswith("Primary Match") for label in reason_labels)
        and candidate.file_category == "source"
    ):
        return "primary"
    if (
        any(label.startswith("Relationship") for label in reason_labels)
        and candidate.file_category == "source"
    ):
        return "related"
    if candidate.file_category == "source":
        return "primary" if candidate.confidence >= SCORE_FILENAME_TERM else "related"
    if candidate.file_category == "test":
        return "test"
    if candidate.file_category == "doc":
        return "doc"
    if candidate.file_category == "config":
        return "config"
    return "infrastructure"
