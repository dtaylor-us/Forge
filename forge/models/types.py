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
