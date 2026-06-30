"""Shared model provider types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    """A model available from a provider."""

    name: str
    provider: str
    details: str | None = None


@dataclass(frozen=True)
class ModelResponse:
    """A text response from a model provider."""

    content: str
    model: str
    provider: str
    truncated: bool = False
    """True when the provider stopped generating because it hit an output
    length limit (token cap or context window) rather than completing
    naturally. Used to distinguish "the model ran out of room" from "the
    model produced a complete but malformed response" — these need very
    different repair prompts and error messages."""
