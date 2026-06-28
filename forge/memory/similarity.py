"""Deterministic similarity scoring between memory items."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from forge.memory.models import MemoryItem
from forge.memory.store import list_items

_STOP_WORDS = frozenset(
    {"a", "an", "the", "and", "or", "of", "in", "is", "it", "to", "for", "with", "on", "at", "by"}
)


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return {t for t in tokens if t not in _STOP_WORDS and len(t) > 1}


@dataclass
class SimilarityReason:
    signal: str
    detail: str
    points: int


@dataclass
class SimilarityResult:
    item: MemoryItem
    score: int
    reasons: list[SimilarityReason] = field(default_factory=list)


def find_similar(
    root: Path,
    query: str,
    *,
    workset: str = "",
    related_files: list[str] | None = None,
    tags: list[str] | None = None,
    max_results: int = 5,
) -> list[SimilarityResult]:
    """
    Find memory items similar to the given context.

    Similarity signals:
    - overlapping related files
    - overlapping worksets
    - common tags
    - common query terms
    - common directory prefixes
    - same repository area (top-level directory)
    """
    query_tokens = _tokenize(query)
    file_set = set(related_files or [])
    dir_set = {str(Path(f).parent) for f in file_set}
    top_dirs = {Path(f).parts[0] for f in file_set if Path(f).parts}
    tag_set = {t.lower() for t in (tags or [])}

    items = list_items(root)
    results: list[SimilarityResult] = []
    for item in items:
        score, reasons = _score_similarity(
            item, query_tokens, workset, file_set, dir_set, top_dirs, tag_set
        )
        if score > 0:
            results.append(SimilarityResult(item=item, score=score, reasons=reasons))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:max_results]


def _score_similarity(
    item: MemoryItem,
    query_tokens: set[str],
    workset: str,
    file_set: set[str],
    dir_set: set[str],
    top_dirs: set[str],
    tag_set: set[str],
) -> tuple[int, list[SimilarityReason]]:
    score = 0
    reasons: list[SimilarityReason] = []

    item_files = set(item.related_files)
    file_overlap = file_set & item_files
    if file_overlap:
        pts = len(file_overlap) * 10
        score += pts
        reasons.append(SimilarityReason("shared_files", f"{len(file_overlap)} shared file(s)", pts))

    item_dirs = {str(Path(f).parent) for f in item.related_files}
    dir_overlap = dir_set & item_dirs
    if dir_overlap:
        pts = len(dir_overlap) * 4
        score += pts
        detail = f"dirs: {', '.join(sorted(dir_overlap))}"
        reasons.append(SimilarityReason("shared_directories", detail, pts))

    item_top_dirs = {Path(f).parts[0] for f in item.related_files if Path(f).parts}
    top_overlap = top_dirs & item_top_dirs
    if top_overlap:
        pts = len(top_overlap) * 3
        score += pts
        detail = f"top dirs: {', '.join(sorted(top_overlap))}"
        reasons.append(SimilarityReason("shared_top_dir", detail, pts))

    all_worksets = {item.workset} | set(item.related_worksets)
    all_worksets.discard("")
    if workset and workset in all_worksets:
        pts = 8
        score += pts
        reasons.append(SimilarityReason("shared_workset", f"workset: {workset}", pts))

    item_tags = {t.lower() for t in item.tags}
    tag_overlap = tag_set & item_tags
    if tag_overlap:
        pts = len(tag_overlap) * 5
        score += pts
        detail = f"tags: {', '.join(sorted(tag_overlap))}"
        reasons.append(SimilarityReason("shared_tags", detail, pts))

    item_tokens = _tokenize(item.title) | _tokenize(item.summary)
    token_overlap = query_tokens & item_tokens
    if token_overlap:
        pts = len(token_overlap) * 2
        score += pts
        detail = f"terms: {', '.join(sorted(token_overlap))}"
        reasons.append(SimilarityReason("query_terms", detail, pts))

    return score, reasons
