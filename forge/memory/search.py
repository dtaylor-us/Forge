"""Deterministic search over engineering memory items."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from forge.memory.models import MemoryItem, MemoryType
from forge.memory.store import list_items

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "in",
        "is",
        "it",
        "to",
        "for",
        "with",
        "on",
        "at",
        "by",
        "as",
        "be",
        "was",
        "are",
        "has",
    }
)


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


@dataclass
class MatchReason:
    signal: str
    detail: str
    points: int


@dataclass
class MemorySearchResult:
    item: MemoryItem
    score: int
    reasons: list[MatchReason] = field(default_factory=list)


def search_memory(
    root: Path,
    query: str,
    *,
    type_filter: MemoryType | None = None,
    max_results: int = 10,
) -> list[MemorySearchResult]:
    """
    Search memory items deterministically by query string.

    Ranking signals (in descending priority):
    - title exact substring match
    - title token overlap
    - tag overlap
    - workset name overlap
    - related file name overlap
    - summary token overlap
    - artifact type match
    """
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        items = list_items(root)
        if type_filter:
            items = [i for i in items if i.type == type_filter]
        return [MemorySearchResult(item=i, score=0) for i in items[:max_results]]

    items = list_items(root)
    if type_filter:
        items = [i for i in items if i.type == type_filter]

    results: list[MemorySearchResult] = []
    for item in items:
        score, reasons = _score_item(item, query, query_tokens)
        if score > 0:
            results.append(MemorySearchResult(item=item, score=score, reasons=reasons))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:max_results]


def _score_item(
    item: MemoryItem,
    query: str,
    query_tokens: set[str],
) -> tuple[int, list[MatchReason]]:
    score = 0
    reasons: list[MatchReason] = []

    title_lower = item.title.lower()
    query_lower = query.lower()

    if query_lower in title_lower:
        pts = 20
        score += pts
        reasons.append(MatchReason("title_exact", f"'{query}' found in title", pts))

    title_tokens = set(_tokenize(item.title))
    overlap = query_tokens & title_tokens
    if overlap:
        pts = len(overlap) * 8
        score += pts
        reasons.append(MatchReason("title_tokens", f"tokens: {', '.join(sorted(overlap))}", pts))

    tag_tokens = set(t.lower() for t in item.tags)
    tag_overlap = query_tokens & tag_tokens
    if tag_overlap:
        pts = len(tag_overlap) * 6
        score += pts
        reasons.append(MatchReason("tags", f"tags: {', '.join(sorted(tag_overlap))}", pts))

    if item.workset:
        workset_tokens = set(_tokenize(item.workset))
        ws_overlap = query_tokens & workset_tokens
        if ws_overlap:
            pts = len(ws_overlap) * 5
            score += pts
            reasons.append(MatchReason("workset", f"workset: {item.workset}", pts))

    file_tokens: set[str] = set()
    for f in item.related_files:
        file_tokens.update(_tokenize(Path(f).name))
    file_overlap = query_tokens & file_tokens
    if file_overlap:
        pts = len(file_overlap) * 4
        score += pts
        detail = f"file tokens: {', '.join(sorted(file_overlap))}"
        reasons.append(MatchReason("related_files", detail, pts))

    summary_tokens = set(_tokenize(item.summary))
    summary_overlap = query_tokens & summary_tokens
    if summary_overlap:
        pts = len(summary_overlap) * 2
        score += pts
        detail = f"summary tokens: {', '.join(sorted(summary_overlap))}"
        reasons.append(MatchReason("summary", detail, pts))

    type_str = item.type.value.lower().replace("_", "")
    if any(t in type_str for t in query_tokens):
        pts = 3
        score += pts
        reasons.append(MatchReason("type", f"artifact type: {item.type.value}", pts))

    return score, reasons
