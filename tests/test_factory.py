"""Provider factory tests."""

from __future__ import annotations

from forge.config.settings import ProviderName, Settings
from forge.models.anthropic import AnthropicProvider
from forge.models.factory import create_provider
from forge.models.ollama import OllamaProvider
from forge.models.openai import OpenAIProvider


def test_create_ollama_provider() -> None:
    provider = create_provider(Settings(provider=ProviderName.OLLAMA))

    assert isinstance(provider, OllamaProvider)


def test_create_openai_provider() -> None:
    provider = create_provider(Settings(provider=ProviderName.OPENAI, openai_api_key="secret"))

    assert isinstance(provider, OpenAIProvider)


def test_create_anthropic_provider() -> None:
    provider = create_provider(
        Settings(provider=ProviderName.ANTHROPIC, anthropic_api_key="secret")
    )

    assert isinstance(provider, AnthropicProvider)
