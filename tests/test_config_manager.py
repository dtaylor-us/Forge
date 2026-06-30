"""Configuration manager tests."""

from __future__ import annotations

import pytest

from forge.config.manager import ConfigManager
from forge.config.settings import ProviderName


def test_default_config_creation_uses_home_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    manager = ConfigManager()

    config = manager.load()

    path = tmp_path / ".forge" / "config.yaml"
    assert config.default_model == "llama3.1:8b"
    assert path.exists()
    assert "provider: ollama" in path.read_text(encoding="utf-8")


def test_load_creates_default_config(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    manager = ConfigManager(path)

    config = manager.load()

    assert config.provider == ProviderName.OLLAMA
    assert config.default_model == "llama3.1:8b"
    assert config.providers["ollama"].timeout_seconds == 120
    assert path.exists()
    assert "provider: ollama" in path.read_text(encoding="utf-8")
    assert "timeout_seconds: 120" in path.read_text(encoding="utf-8")


def test_load_reads_provider_endpoint(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            [
                "provider: ollama",
                "default_model: qwen2.5-coder:14b",
                "providers:",
                "  ollama:",
                "    endpoint: http://localhost:11434",
                "    timeout_seconds: 180",
            ]
        ),
        encoding="utf-8",
    )

    config = ConfigManager(path).load()

    assert config.provider == ProviderName.OLLAMA
    assert config.default_model == "qwen2.5-coder:14b"
    assert config.providers["ollama"].endpoint == "http://localhost:11434"
    assert config.providers["ollama"].timeout_seconds == 180


def test_load_reads_custom_ollama_endpoint(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            [
                "provider: ollama",
                "default_model: llama3.1:8b",
                "providers:",
                "  ollama:",
                "    endpoint: http://127.0.0.1:11435",
            ]
        ),
        encoding="utf-8",
    )

    config = ConfigManager(path).load()

    assert config.providers["ollama"].endpoint == "http://127.0.0.1:11435"


def test_load_defaults_ollama_timeout_when_missing(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            [
                "provider: ollama",
                "default_model: qwen2.5-coder:14b",
                "providers:",
                "  ollama:",
                "    endpoint: http://localhost:11434",
            ]
        ),
        encoding="utf-8",
    )

    config = ConfigManager(path).load()

    assert config.providers["ollama"].timeout_seconds == 120


def test_load_backfills_max_tokens_and_context_window_for_existing_config(tmp_path) -> None:
    """A config.yaml written before max_tokens/context_window existed (e.g. by
    an earlier Forge version) must not silently fall back to None — which,
    pre-fix, meant Anthropic/OpenAI used a hardcoded 1024-token cap and Ollama
    used the server's own default context window, both of which can truncate
    a model's response mid-generation with no visible error."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            [
                "provider: ollama",
                "default_model: qwen2.5-coder:32b",
                "providers:",
                "  ollama:",
                "    endpoint: http://localhost:11434",
                "    timeout_seconds: 480",
            ]
        ),
        encoding="utf-8",
    )

    config = ConfigManager(path).load()

    assert config.providers["ollama"].max_tokens == 4096
    assert config.providers["ollama"].context_window == 8192
    # The field that *was* present in the file must still be respected.
    assert config.providers["ollama"].timeout_seconds == 480


def test_load_respects_explicit_max_tokens_and_context_window(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            [
                "provider: ollama",
                "providers:",
                "  ollama:",
                "    max_tokens: 16000",
                "    context_window: 32768",
            ]
        ),
        encoding="utf-8",
    )

    config = ConfigManager(path).load()

    assert config.providers["ollama"].max_tokens == 16000
    assert config.providers["ollama"].context_window == 32768


def test_anthropic_and_openai_get_non_trivial_max_tokens_default(tmp_path) -> None:
    """Anthropic/OpenAI provider construction must never see max_tokens=None
    flow down to the provider class's own 1024 default for a fresh project
    config — 1024 is too low for patch/diff generation."""
    path = tmp_path / "config.yaml"
    path.write_text("provider: anthropic\n", encoding="utf-8")

    config = ConfigManager(path).load()

    assert config.providers["anthropic"].max_tokens == 8192


def test_render_config_round_trips_max_tokens_and_context_window(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    ConfigManager(path).load()  # creates the default file

    content = path.read_text(encoding="utf-8")
    assert "max_tokens: 4096" in content
    assert "context_window: 8192" in content

    reloaded = ConfigManager(path).load()
    assert reloaded.providers["ollama"].max_tokens == 4096
    assert reloaded.providers["ollama"].context_window == 8192


def test_load_ignores_invalid_timeout_and_uses_default(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            [
                "provider: ollama",
                "providers:",
                "  ollama:",
                "    timeout_seconds: not-a-number",
            ]
        ),
        encoding="utf-8",
    )

    config = ConfigManager(path).load()

    assert config.providers["ollama"].timeout_seconds == 120


def test_load_invalid_provider_fails_clearly(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("provider: unsupported\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported"):
        ConfigManager(path).load()


def test_set_default_model_persists_config(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    manager = ConfigManager(path)

    manager.set_default_model("qwen2.5-coder:14b")

    assert "default_model: qwen2.5-coder:14b" in path.read_text(encoding="utf-8")
