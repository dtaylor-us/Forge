"""Telemetry helpers for model interactions."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from types import TracebackType
from typing import Any

from forge.models.types import ModelResponse


@dataclass(frozen=True)
class InteractionMetrics:
    """Log-safe metrics for one model interaction."""

    provider: str
    endpoint: str | None
    model: str
    elapsed_ms: int
    prompt_size: int
    response_size: int | None
    prompt_tokens_estimate: int
    response_tokens_estimate: int | None
    error: str | None = None


class ModelInteractionTelemetry:
    """Capture log-safe telemetry around a model call."""

    def __init__(
        self, logger: Any, *, provider: str, endpoint: str | None, model: str, prompt: str
    ) -> None:
        self._logger = logger
        self._provider = provider
        self._endpoint = endpoint
        self._model = model
        self._prompt = prompt
        self._started_at = 0.0

    def __enter__(self) -> ModelInteractionTelemetry:
        self._started_at = perf_counter()
        self._logger.info(
            "models.ask.start",
            provider=self._provider,
            endpoint=self._endpoint,
            model=self._model,
            prompt_size=len(self._prompt),
            prompt_tokens_estimate=estimate_tokens(self._prompt),
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if exc is not None:
            self.log_failure(exc)
        return False

    def log_success(self, response: ModelResponse) -> None:
        """Log completion metrics without recording prompt or response content."""
        metrics = self._metrics(
            response_size=len(response.content),
            response_tokens_estimate=estimate_tokens(response.content),
        )
        self._logger.info("models.ask.complete", **metrics.__dict__)

    def log_failure(self, exc: BaseException) -> None:
        """Log failure metrics without recording prompt content."""
        metrics = self._metrics(
            response_size=None,
            response_tokens_estimate=None,
            error=type(exc).__name__,
        )
        self._logger.error("models.ask.error", **metrics.__dict__)

    def _metrics(
        self,
        *,
        response_size: int | None,
        response_tokens_estimate: int | None,
        error: str | None = None,
    ) -> InteractionMetrics:
        return InteractionMetrics(
            provider=self._provider,
            endpoint=self._endpoint,
            model=self._model,
            elapsed_ms=max(0, round((perf_counter() - self._started_at) * 1000)),
            prompt_size=len(self._prompt),
            response_size=response_size,
            prompt_tokens_estimate=estimate_tokens(self._prompt),
            response_tokens_estimate=response_tokens_estimate,
            error=error,
        )


def estimate_tokens(text: str) -> int:
    """Return a conservative local estimate without provider-specific tokenizers."""
    if not text:
        return 0
    return max(1, round(len(text) / 4))
