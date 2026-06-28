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
