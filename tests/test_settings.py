"""Settings tests."""

from __future__ import annotations

from forge.config.settings import ProviderName, Settings


def test_settings_defaults_to_ollama(monkeypatch) -> None:
    monkeypatch.delenv("FORGE_PROVIDER", raising=False)
    monkeypatch.delenv("FORGE_MODEL", raising=False)

    settings = Settings.from_env()

    assert settings.provider == ProviderName.OLLAMA
    assert settings.model == "llama3.1:8b"


def test_settings_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("FORGE_PROVIDER", "anthropic")
    monkeypatch.setenv("FORGE_MODEL", "claude-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")

    settings = Settings.from_env()

    assert settings.provider == ProviderName.ANTHROPIC
    assert settings.model == "claude-test"
    assert settings.anthropic_api_key == "secret"
