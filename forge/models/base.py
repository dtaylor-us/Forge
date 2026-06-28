"""Model provider contract."""

from __future__ import annotations

from typing import Protocol

from forge.models.types import ModelInfo, ModelResponse


class ModelProvider(Protocol):
    """Interface implemented by all model providers."""

    name: str
    endpoint: str

    def list_models(self) -> list[ModelInfo]:
        """Return models available from this provider."""

    def ask(
        self,
        prompt: str,
        model: str,
        timeout_seconds: int | None = None,
    ) -> ModelResponse:
        """Send a prompt to a model and return text."""

    def normalize_model_name(self, model: str) -> str:
        """Return this provider's canonical model identifier."""
