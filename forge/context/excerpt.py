"""Relevant excerpt extraction from file content."""

from __future__ import annotations

import re

_OMIT_MARKER = "... (lines omitted) ..."


def extract_excerpts(
    content: str,
    query_tokens: list[str],
    *,
    max_lines: int = 120,
    include_full: bool = False,
) -> list[str]:
    """Return a list of excerpt lines from content.

    Includes:
    - First meaningful lines (up to 20)
    - Lines around query token matches (±3 context lines)
    Caps total output at max_lines unless include_full is True.
    """
    lines = content.splitlines()
    if include_full:
        return lines

    if not lines:
        return []

    total = len(lines)
    selected: set[int] = set()

    # Always include leading non-blank lines (up to 20)
    count = 0
    for i, line in enumerate(lines):
        if count >= 20:
            break
        selected.add(i)
        if line.strip():
            count += 1

    # Add context around query matches
    if query_tokens:
        pattern = re.compile("|".join(re.escape(t) for t in query_tokens), re.IGNORECASE)
        for i, line in enumerate(lines):
            if pattern.search(line):
                for j in range(max(0, i - 3), min(total, i + 4)):
                    selected.add(j)

    # Sort and cap
    sorted_indices = sorted(selected)

    # Respect max_lines
    if len(sorted_indices) > max_lines:
        sorted_indices = sorted_indices[:max_lines]

    # Render with omit markers
    result: list[str] = []
    prev: int | None = None
    for idx in sorted_indices:
        if prev is not None and idx > prev + 1:
            result.append(_OMIT_MARKER)
        result.append(lines[idx])
        prev = idx

    if sorted_indices and sorted_indices[-1] < total - 1:
        result.append(_OMIT_MARKER)

    return result
