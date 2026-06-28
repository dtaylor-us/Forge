"""Provider construction."""

from __future__ import annotations

from forge.config.settings import ProviderName, Settings
from forge.models.anthropic import AnthropicProvider
from forge.models.base import ModelProvider
from forge.models.ollama import OllamaProvider
from forge.models.openai import OpenAIProvider


def create_provider(settings: Settings) -> ModelProvider:
    """Create the configured model provider."""
    if settings.provider == ProviderName.OLLAMA:
        return OllamaProvider(settings.ollama_host)
    if settings.provider == ProviderName.OPENAI:
        return OpenAIProvider(
            settings.openai_api_key,
            base_url=settings.openai_base_url,
            max_tokens=settings.max_tokens,
        )
    if settings.provider == ProviderName.ANTHROPIC:
        return AnthropicProvider(
            settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
            max_tokens=settings.max_tokens,
        )
    raise ValueError(f"Unsupported provider: {settings.provider}")
