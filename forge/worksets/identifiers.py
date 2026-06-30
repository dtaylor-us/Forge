"""Deterministic engineering identifier recognition."""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)*")
_CAMEL_PART_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+")

TEST_SUFFIXES = (
    "IntegrationTest",
    "FeatureTest",
    "AcceptanceTest",
    "Specification",
    "Tests",
    "Test",
    "Spec",
    "IT",
)


def extract_identifiers(text: str) -> list[str]:
    """Return identifier-like terms in stable first-seen order."""
    seen: set[str] = set()
    identifiers: list[str] = []
    for match in _IDENTIFIER_RE.finditer(text):
        value = match.group(0).strip("_-")
        if len(value) < 2:
            continue
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        identifiers.append(value)
    return identifiers


def split_identifier(identifier: str) -> list[str]:
    """Split CamelCase/snake/kebab identifiers while preserving useful compounds."""
    chunks: list[str] = []
    for piece in re.split(r"[_\-\s]+", identifier):
        chunks.extend(part for part in _CAMEL_PART_RE.findall(piece) if part)
    return chunks


def expand_identifier(identifier: str) -> list[str]:
    """Return weighted search forms for an engineering identifier."""
    parts = split_identifier(identifier)
    terms = [identifier, *parts]
    if len(parts) >= 2:
        terms.append("".join(parts[:2]))
    return _dedupe(terms)


def is_test_identifier(identifier: str) -> bool:
    """Return whether an identifier names a test/spec artifact."""
    normalized = identifier.replace("_", "").replace("-", "")
    return any(normalized.endswith(suffix) for suffix in TEST_SUFFIXES)


def implementation_bases(identifier: str) -> list[str]:
    """Derive implementation names from a test identifier."""
    bases = [identifier]
    for suffix in TEST_SUFFIXES:
        if identifier.endswith(suffix) and len(identifier) > len(suffix):
            bases.append(identifier[: -len(suffix)])
            break
    parts = split_identifier(bases[-1])
    if len(parts) >= 2:
        bases.append("".join(parts[:2]))
    return _dedupe([base for base in bases if base])


def normalize_identifier(value: str) -> str:
    """Normalize an identifier or filename stem for deterministic comparisons."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result
