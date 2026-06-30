"""Deterministic query parsing for workset selection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from forge.worksets.identifiers import (
    expand_identifier,
    extract_identifiers,
    is_test_identifier,
    split_identifier,
)

SUPPORTED_INTENTS = {
    "feature",
    "bugfix",
    "refactor",
    "documentation",
    "investigation",
    "search",
    "generic",
}

ACTION_INTENTS = {
    "fix": "bugfix",
    "repair": "bugfix",
    "debug": "bugfix",
    "add": "feature",
    "implement": "feature",
    "create": "feature",
    "support": "feature",
    "allow": "feature",
    "enable": "feature",
    "disable": "feature",
    "update": "generic",
    "change": "generic",
    "modify": "generic",
    "remove": "refactor",
    "rename": "refactor",
    "refactor": "refactor",
    "investigate": "investigation",
}
ACTION_VERBS = frozenset(ACTION_INTENTS)
DOC_TERMS = frozenset({"doc", "docs", "documentation", "readme", "guide", "adr"})
TEST_TERMS = frozenset({"test", "tests", "spec", "specs", "fixture", "fixtures", "regression"})
CONFIG_TERMS = frozenset({"config", "configuration", "settings", "yaml", "toml", "json"})
BUILD_TERMS = frozenset({"build", "docker", "dockerfile", "makefile", "gradle", "maven", "pom"})
STOP_TOKENS = frozenset({"the", "a", "an", "of", "in", "to", "for", "and", "or", "is"})

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# Term weights are scoring multipliers (relative to MAX_TERM_WEIGHT) applied in
# forge.worksets.scoring. A full, distinctive identifier ("SessionControllerIntegrationTest")
# is far more specific than one of its decomposed parts ("Session", "Test") and must not
# contribute the same amount of score when it shows up as a content/filename/path match —
# decomposed parts are common English/engineering words that otherwise flood scoring with
# false positives across an entire codebase.
TERM_WEIGHT_FULL = 5
TERM_WEIGHT_COMPOUND = 3
TERM_WEIGHT_PART = 1
TERM_WEIGHT_TOKEN = 1
MAX_TERM_WEIGHT = TERM_WEIGHT_FULL


@dataclass(frozen=True)
class SearchTerm:
    """A deterministic query term with a scoring weight."""

    value: str
    weight: int = 1
    kind: str = "token"


@dataclass
class WorksetQuery:
    """Parsed workset query used by deterministic selection stages."""

    raw_query: str
    intent: str
    subject: str
    search_terms: list[SearchTerm] = field(default_factory=list)
    ignored_terms: list[str] = field(default_factory=list)
    include_tests: bool = False
    include_docs: bool = False
    include_configs: bool = False
    include_build_files: bool = False
    identifiers: list[str] = field(default_factory=list)

    @property
    def tokens(self) -> list[str]:
        """Return unique lowercase search terms for backward-compatible display."""
        seen: set[str] = set()
        values: list[str] = []
        for term in self.search_terms:
            value = term.value.lower()
            if value not in seen:
                seen.add(value)
                values.append(value)
        return values


def parse_query(
    query: str,
    *,
    include_tests: bool = False,
    workflow: str | None = None,
) -> WorksetQuery:
    """Parse a natural-language task into deterministic workset search inputs."""
    raw_tokens = _TOKEN_RE.findall(query)
    lower_tokens = [token.lower() for token in raw_tokens]
    ignored_terms = [
        token for token in lower_tokens if token in ACTION_VERBS or token in STOP_TOKENS
    ]

    intent = _intent_from(workflow, lower_tokens)
    identifiers = [
        identifier
        for identifier in extract_identifiers(query)
        if identifier.lower() not in ACTION_VERBS and identifier.lower() not in STOP_TOKENS
    ]
    subject = _subject_from(identifiers, raw_tokens)

    include_tests = (
        include_tests
        or intent == "bugfix"
        or any(token in TEST_TERMS for token in lower_tokens)
        or any(is_test_identifier(identifier) for identifier in identifiers)
    )
    include_docs = any(token in DOC_TERMS for token in lower_tokens) or intent == "documentation"
    include_configs = any(token in CONFIG_TERMS for token in lower_tokens)
    include_build_files = any(token in BUILD_TERMS for token in lower_tokens)

    terms = _terms_from(identifiers, raw_tokens, ignored_terms)
    return WorksetQuery(
        raw_query=query,
        intent=intent,
        subject=subject,
        search_terms=terms,
        ignored_terms=ignored_terms,
        include_tests=include_tests,
        include_docs=include_docs,
        include_configs=include_configs,
        include_build_files=include_build_files,
        identifiers=identifiers,
    )


def _intent_from(workflow: str | None, lower_tokens: list[str]) -> str:
    if workflow in SUPPORTED_INTENTS:
        return workflow
    if any(token in {"doc", "docs", "documentation"} for token in lower_tokens):
        return "documentation"
    for token in lower_tokens:
        intent = ACTION_INTENTS.get(token)
        if intent:
            return intent
    if lower_tokens:
        return "search"
    return "generic"


def _subject_from(identifiers: list[str], raw_tokens: list[str]) -> str:
    # Prefer a CamelCase/PascalCase identifier (a real class/file name) over a generic
    # lowercase word that merely survived the action-verb/stop-word filter (e.g. "tests" in
    # "add tests for PaymentController" should not become the subject ahead of
    # "PaymentController").
    for identifier in identifiers:
        if _looks_like_code_identifier(identifier):
            return identifier
    if identifiers:
        return identifiers[0]
    for token in raw_tokens:
        lower = token.lower()
        if lower not in ACTION_VERBS and lower not in STOP_TOKENS:
            return token
    return ""


def _looks_like_code_identifier(identifier: str) -> bool:
    """Return whether an identifier looks like a class/file name rather than a plain word."""
    if any(ch.isupper() for ch in identifier[1:]):
        return True
    return "_" in identifier or "-" in identifier


def _terms_from(
    identifiers: list[str], raw_tokens: list[str], ignored_terms: list[str]
) -> list[SearchTerm]:
    terms: list[SearchTerm] = []
    ignored = set(ignored_terms)

    for identifier in identifiers:
        expanded = expand_identifier(identifier)
        parts = split_identifier(identifier)
        compound = "".join(parts[:2]) if len(parts) >= 2 else None
        for index, value in enumerate(expanded):
            if index == 0:
                weight, kind = TERM_WEIGHT_FULL, "identifier"
            elif compound is not None and value == compound:
                weight, kind = TERM_WEIGHT_COMPOUND, "identifier_compound"
            else:
                weight, kind = TERM_WEIGHT_PART, "identifier_part"
            terms.append(SearchTerm(value=value, weight=weight, kind=kind))

    for token in raw_tokens:
        lower = token.lower()
        if lower in ignored or len(lower) < 2:
            continue
        if any(term.value.lower() == lower for term in terms):
            continue
        terms.append(SearchTerm(value=token, weight=TERM_WEIGHT_TOKEN, kind="token"))

    return _dedupe_terms(terms)


def _dedupe_terms(terms: list[SearchTerm]) -> list[SearchTerm]:
    by_value: dict[str, SearchTerm] = {}
    for term in terms:
        key = term.value.lower()
        existing = by_value.get(key)
        if existing is None or term.weight > existing.weight:
            by_value[key] = term
    return list(by_value.values())
