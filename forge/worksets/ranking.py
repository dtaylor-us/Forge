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


def assemble_workset(
    candidates: list[WorksetCandidate],
    *,
    max_results: int,
    infrastructure_quota: int = DEFAULT_INFRASTRUCTURE_QUOTA,
) -> list[WorksetCandidate]:
    """Assemble an intentionally ordered workset from scored candidates."""
    relevant = [candidate for candidate in candidates if candidate.confidence > 0]
    has_implementation = any(
        candidate.file_category == "source" and candidate.confidence >= 50 for candidate in relevant
    )

    ordered = sorted(
        relevant,
        key=lambda c: (
            _GROUP_ORDER.get(c.rank_group, 99),
            -c.confidence,
            -c.importance,
            str(c.path),
        ),
    )

    assembled: list[WorksetCandidate] = []
    infrastructure_count = 0
    for candidate in ordered:
        if has_implementation and is_infrastructure_file(candidate.path):
            if infrastructure_count >= infrastructure_quota:
                continue
            infrastructure_count += 1
        assembled.append(candidate)
        if len(assembled) >= max_results:
            break

    return assembled
