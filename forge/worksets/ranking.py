"""Deterministic workset ranking and assembly."""

from __future__ import annotations

from forge.worksets.candidate import WorksetCandidate
from forge.worksets.scoring import is_infrastructure_file

DEFAULT_INFRASTRUCTURE_QUOTA = 3

_GROUP_ORDER = {
    "primary": 0,
    "related": 1,
    "test": 2,
    "doc": 3,
    "config": 4,
    "infrastructure": 5,
    "other": 6,
}


def _sort_key(candidate: WorksetCandidate) -> tuple[int, int, int, str]:
    return (
        _GROUP_ORDER.get(candidate.rank_group, 99),
        -candidate.confidence,
        -candidate.importance,
        str(candidate.path),
    )


def assemble_workset(
    candidates: list[WorksetCandidate],
    *,
    max_results: int,
    infrastructure_quota: int = DEFAULT_INFRASTRUCTURE_QUOTA,
) -> list[WorksetCandidate]:
    """Assemble an intentionally ordered workset from scored candidates.

    Required candidates (files force-included by the exact-target locator,
    see `forge.worksets.locator.locate_exact_targets`) are reserved ahead of
    `max_results` truncation: they are placed first, deterministically
    ordered among themselves, and are never displaced by ordinary candidates
    competing for the remaining slots.
    """
    relevant = [
        candidate for candidate in candidates if candidate.confidence > 0 or candidate.required
    ]
    has_implementation = any(
        candidate.file_category == "source" and candidate.confidence >= 50 for candidate in relevant
    )

    required = sorted((c for c in relevant if c.required), key=_sort_key)
    optional = sorted((c for c in relevant if not c.required), key=_sort_key)

    assembled: list[WorksetCandidate] = list(required)
    infrastructure_count = 0
    for candidate in optional:
        if len(assembled) >= max_results:
            break
        if has_implementation and is_infrastructure_file(candidate.path):
            if infrastructure_count >= infrastructure_quota:
                continue
            infrastructure_count += 1
        assembled.append(candidate)

    return assembled
