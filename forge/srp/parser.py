"""Parse SEARCH/REPLACE blocks from raw model output."""

from __future__ import annotations

import re

from forge.srp.models import SearchReplaceBlock

# Block delimiters — kept as constants so tests and prompts can stay in sync.
SEARCH_MARKER = "<<<<<<< SEARCH"
SEP_MARKER = "======="
REPLACE_MARKER = ">>>>>>> REPLACE"

# A line is treated as a file-path candidate when it looks like a relative
# path: contains at least one "/" or ".", has no leading whitespace (so diff
# hunk lines like " some code" are excluded), and is not one of the markers.
_FILEPATH_RE = re.compile(r"^[^\s].*[/.].*$")
_ALL_MARKERS = frozenset({SEARCH_MARKER, SEP_MARKER, REPLACE_MARKER})


class ParseError(Exception):
    """Raised when model output contains no parseable SEARCH/REPLACE blocks."""


def parse_search_replace_blocks(content: str) -> list[SearchReplaceBlock]:
    """Parse all SEARCH/REPLACE blocks from ``content``.

    The expected format for each block is::

        path/to/File.java
        <<<<<<< SEARCH
        <exact lines to find>
        =======
        <replacement lines>
        >>>>>>> REPLACE

    Rules:
    - The filepath line must appear immediately before ``<<<<<<< SEARCH``
      (ignoring blank lines between them).
    - Multiple blocks may target the same file.
    - Blocks with an empty SEARCH section are treated as file-creation blocks.
    - Returns an empty list (not an exception) when no blocks are found so that
      callers can use the empty list as a signal to enter the repair loop.
    """
    lines = content.splitlines(keepends=False)
    blocks: list[SearchReplaceBlock] = []
    i = 0
    n = len(lines)

    while i < n:
        # Locate the next SEARCH marker.
        if lines[i].strip() != SEARCH_MARKER:
            i += 1
            continue

        # Walk backwards from here to find the nearest non-blank, non-marker
        # line — that is the file path.
        file_path: str | None = None
        for j in range(i - 1, -1, -1):
            candidate = lines[j].strip()
            if not candidate:
                continue  # skip blank separator lines
            if candidate in _ALL_MARKERS:
                break  # bumped into another block's REPLACE marker
            if _FILEPATH_RE.match(candidate):
                file_path = candidate
            break  # first non-blank line wins regardless

        if file_path is None:
            # No file path found before this marker — skip it.
            i += 1
            continue

        # Collect the SEARCH content up to the separator.
        i += 1
        search_lines: list[str] = []
        while i < n and lines[i].strip() != SEP_MARKER:
            search_lines.append(lines[i])
            i += 1

        if i >= n:
            break  # truncated block

        i += 1  # skip =======

        # Collect the REPLACE content up to >>>>>>> REPLACE.
        replace_lines: list[str] = []
        while i < n and lines[i].strip() != REPLACE_MARKER:
            replace_lines.append(lines[i])
            i += 1

        if i < n:
            i += 1  # skip >>>>>>> REPLACE

        # Strip a single leading/trailing blank line that some models add
        # inside the fence — but preserve internal blank lines exactly.
        search_text = _trim_fence_blank(search_lines)
        replace_text = _trim_fence_blank(replace_lines)

        blocks.append(
            SearchReplaceBlock(
                file_path=file_path,
                search=search_text,
                replace=replace_text,
            )
        )

    return blocks


def _trim_fence_blank(lines: list[str]) -> str:
    """Join lines, stripping at most one leading and one trailing blank line."""
    if lines and lines[0] == "":
        lines = lines[1:]
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return "\n".join(lines)
