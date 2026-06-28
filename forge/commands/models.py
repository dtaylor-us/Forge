"""Model command handlers."""

from __future__ import annotations

from forge.models.manager import ModelManager
from forge.models.types import ModelInfo, ModelResponse


def list_models(manager: ModelManager | None = None) -> list[ModelInfo]:
    """List models from the configured provider."""
    return (manager or ModelManager()).list_models()


def ask_model(
    prompt: str,
    model: str | None = None,
    timeout_seconds: int | None = None,
    manager: ModelManager | None = None,
) -> ModelResponse:
    """Send a prompt to the configured model provider."""
    return (manager or ModelManager()).ask(
        prompt=prompt,
        model=model,
        timeout_seconds=timeout_seconds,
    )
