"""Deterministic exact-target locator for workset selection.

The relationship-based scorer in `forge.worksets.relationships` recognizes
related identifiers (e.g. "SessionController" derived from
"SessionControllerIntegrationTest") and scores any file across the whole
repository that shares that name. In a multi-module/multi-pillar repository
that is exactly the problem: same-named concepts in unrelated modules
("lens-api/.../SessionController.java", "axiom-ui/.../SessionController.ts")
score identically to the real target and can outrank or even displace it once
`max_results` truncation is applied.

This module runs *before* normal candidate scoring and answers a narrower,
higher-confidence question: does the query name a file that exists verbatim
in the repository? If so, that file (or files, if the name is ambiguous) is
located deterministically by exact filename-stem match and is force-included
as a required candidate, and — when every exact match lives under the same
top-level module — that module becomes the affinity root used to boost
in-module candidates and demote same-named candidates elsewhere.
"""

from __future__ import annotations

from pathlib import Path

from forge.worksets.identifiers import is_test_identifier, normalize_identifier
from forge.worksets.query import WorksetQuery


def strong_identifiers(query: WorksetQuery) -> list[str]:
    """Return query identifiers specific enough to anchor an exact-target lock.

    A "strong" identifier looks like a real code symbol — CamelCase/PascalCase,
    snake_case/kebab-case, or a recognized test suffix — rather than a generic
    lowercase word that merely survived stop-word/action-verb filtering (e.g.
    "fix" or "session" alone should never force-lock a file).
    """
    return [
        identifier
        for identifier in query.identifiers
        if _looks_like_code_identifier(identifier) or is_test_identifier(identifier)
    ]


def _looks_like_code_identifier(identifier: str) -> bool:
    if any(ch.isupper() for ch in identifier[1:]):
        return True
    return "_" in identifier or "-" in identifier


def module_root_of(path: Path) -> str:
    """Return the top-level path segment used as a module/pillar root.

    A bare filename (no parent directory) has no module root to anchor on.
    """
    parts = path.parts
    return parts[0] if len(parts) > 1 else ""


def locate_exact_targets(
    files: list[Path], query: WorksetQuery
) -> tuple[list[Path], str | None]:
    """Force-locate files whose name exactly matches a strong query identifier.

    Returns `(exact_matches, module_root)`. `exact_matches` contains every file
    whose normalized stem exactly equals a normalized strong identifier,
    in stable input order. `module_root` is the shared top-level directory of
    those matches when (and only when) every match lives under the *same*
    top-level module — otherwise affinity is ambiguous and `module_root` is
    `None`, per the rule that module affinity must never be guessed.
    """
    identifiers = strong_identifiers(query)
    if not identifiers:
        return [], None

    normalized_targets = {normalize_identifier(identifier) for identifier in identifiers}

    matches = [path for path in files if normalize_identifier(path.stem) in normalized_targets]
    if not matches:
        return [], None

    module_roots = {module_root_of(path) for path in matches}
    module_roots.discard("")
    module_root = next(iter(module_roots)) if len(module_roots) == 1 else None
    return matches, module_root
