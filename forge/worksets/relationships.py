"""Deterministic workset relationship expansion."""

from __future__ import annotations

from pathlib import Path

from forge.worksets.identifiers import (
    implementation_bases,
    normalize_identifier,
    split_identifier,
)
from forge.worksets.query import WorksetQuery

RELATED_SUFFIXES = (
    "Controller",
    "Service",
    "Repository",
    "Facade",
    "Api",
    "Mapper",
    "Client",
    "Provider",
    "Request",
    "Response",
)


def relationship_targets(query: WorksetQuery) -> list[str]:
    """Return deterministic related filename stems for a parsed query."""
    targets: list[str] = []
    for identifier in query.identifiers:
        bases = implementation_bases(identifier)
        targets.extend(bases)
        for base in bases:
            root = _domain_root(base)
            if not root:
                continue
            targets.extend(f"{root}{suffix}" for suffix in RELATED_SUFFIXES)
    return _dedupe(targets)


def relationship_for_path(path: Path, targets: list[str]) -> str | None:
    """Return the relationship target matched by a path, if any."""
    stem = normalize_identifier(path.stem)
    for target in targets:
        normalized = normalize_identifier(target)
        if stem == normalized:
            return target
    return None


def _domain_root(identifier: str) -> str:
    parts = split_identifier(identifier)
    if not parts:
        return ""
    if len(parts) >= 2 and parts[-1] in RELATED_SUFFIXES:
        return "".join(parts[:-1])
    return parts[0]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result
