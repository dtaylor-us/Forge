"""Workset candidate data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CandidateReason:
    """A single scored reason a file was selected."""

    label: str
    score: int


@dataclass
class WorksetCandidate:
    """A file candidate with an explainable score."""

    path: Path
    score: int
    reasons: list[CandidateReason] = field(default_factory=list)
    content_matches: list[str] = field(default_factory=list)
    file_category: str = "source"
    confidence: int = 0
    importance: int = 0
    rank_group: str = "other"

    def add_reason(self, label: str, points: int) -> None:
        if any(reason.label == label for reason in self.reasons):
            return
        self.reasons.append(CandidateReason(label=label, score=points))
        self.score += points


@dataclass
class WorksetSuggestion:
    """The full result of a workset suggestion query."""

    query: str
    tokens: list[str]
    candidates: list[WorksetCandidate]
    root: Path
