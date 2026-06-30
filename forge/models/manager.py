"""High-level model management."""

from __future__ import annotations

import os
from difflib import get_close_matches

from forge.config.manager import ConfigManager, ForgeConfig, ProviderConfig
from forge.config.settings import ProviderName
from forge.models.anthropic import AnthropicProvider
from forge.models.base import ModelProvider
from forge.models.errors import ModelProviderError
from forge.models.ollama import OllamaProvider
from forge.models.openai import OpenAIProvider
from forge.models.telemetry import ModelInteractionTelemetry
from forge.models.types import ModelInfo, ModelResponse
from forge.utils.logging import get_logger

logger = get_logger(__name__)


def _model_timeout_heuristic(model: str, fallback: int = 300) -> int:
    """Return a recommended timeout in seconds based on model name size hints."""
    name = model.lower()
    for suffix, seconds in [
        ("70b", 600),
        ("34b", 480),
        ("32b", 480),
        ("30b", 480),
        ("22b", 360),
        ("14b", 300),
        ("13b", 270),
        ("7b", 180),
        ("3b", 120),
    ]:
        if suffix in name:
            return seconds
    return fallback


class ModelNotFoundError(ModelProviderError):
    """Raised when the configured provider does not expose a requested model."""

    def __init__(self, requested_model: str, suggestions: list[ModelInfo]) -> None:
        super().__init__(f"Model not found: {requested_model}")
        self.requested_model = requested_model
        self.suggestions = suggestions

    def __str__(self) -> str:
        return f"Model not found: {self.requested_model}"


class ModelManager:
    """Coordinate model configuration, provider selection, and validation."""

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self.config_manager = config_manager or ConfigManager()

    def config(self) -> ForgeConfig:
        """Return the loaded Forge configuration."""
        return self.config_manager.load()

    def default_model(self) -> str:
        """Return the configured default model."""
        return self.config().default_model

    def list_models(self) -> list[ModelInfo]:
        """List models installed for the configured provider."""
        provider = self._provider(self.config())
        logger.info(
            "models.list",
            provider=provider.name,
            endpoint=getattr(provider, "endpoint", None),
        )
        return provider.list_models()

    def use_model(self, model: str) -> ForgeConfig:
        """Validate and persist a model as the configured default."""
        self.validate_model(model)
        return self.config_manager.set_default_model(model)

    def ask(
        self,
        prompt: str,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> ModelResponse:
        """Ask the configured provider with either an override or the default model."""
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ModelProviderError("Timeout must be greater than zero seconds.")
        config = self.config()
        provider = self._provider(config, timeout_seconds=timeout_seconds)
        requested_model = model or config.default_model
        resolved_model = self._provider_model_name(provider, requested_model)
        self._validate_model_exists(provider, resolved_model)
        with ModelInteractionTelemetry(
            logger,
            provider=provider.name,
            endpoint=getattr(provider, "endpoint", None),
            model=resolved_model,
            prompt=prompt,
        ) as telemetry:
            response = provider.ask(
                prompt=prompt,
                model=resolved_model,
                timeout_seconds=timeout_seconds,
            )
            telemetry.log_success(response)
            return response

    def validate_model(self, model: str) -> ModelInfo:
        """Return installed model info when the requested model exists."""
        provider = self._provider(self.config())
        resolved_model = self._provider_model_name(provider, model)
        return self._validate_model_exists(provider, resolved_model)

    def _validate_model_exists(self, provider: ModelProvider, model: str) -> ModelInfo:
        installed = provider.list_models()
        for candidate in installed:
            if candidate.name == model:
                return candidate
        names = [candidate.name for candidate in installed]
        suggestion_names = set(get_close_matches(model, names, n=5, cutoff=0.35))
        suggestions = [candidate for candidate in installed if candidate.name in suggestion_names]
        raise ModelNotFoundError(requested_model=model, suggestions=suggestions)

    def _provider(
        self,
        config: ForgeConfig,
        timeout_seconds: int | None = None,
    ) -> ModelProvider:
        provider_config = config.providers.get(config.provider.value, ProviderConfig())
        endpoint = provider_config.endpoint
        if config.provider == ProviderName.OLLAMA:
            configured = timeout_seconds or provider_config.timeout_seconds
            if configured is None:
                configured = _model_timeout_heuristic(config.default_model, fallback=300)
            return OllamaProvider(endpoint or "http://localhost:11434", timeout_seconds=configured)
        if config.provider == ProviderName.OPENAI:
            return OpenAIProvider(
                os.getenv("OPENAI_API_KEY"),
                base_url=endpoint or "https://api.openai.com/v1",
            )
        if config.provider == ProviderName.ANTHROPIC:
            return AnthropicProvider(
                os.getenv("ANTHROPIC_API_KEY"),
                base_url=endpoint or "https://api.anthropic.com/v1",
            )
        raise ValueError(f"Unsupported provider: {config.provider}")

    @staticmethod
    def _provider_model_name(provider: ModelProvider, model: str) -> str:
        normalizer = getattr(provider, "normalize_model_name", None)
        if callable(normalizer):
            return str(normalizer(model))
        return model
