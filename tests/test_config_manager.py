"""Configuration manager tests."""

from __future__ import annotations

from forge.config.manager import ConfigManager
from forge.config.settings import ProviderName


def test_load_creates_default_config(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    manager = ConfigManager(path)

    config = manager.load()

    assert config.provider == ProviderName.OLLAMA
    assert config.default_model == "llama3.1:8b"
    assert path.exists()
    assert "provider: ollama" in path.read_text(encoding="utf-8")


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
            ]
        ),
        encoding="utf-8",
    )

    config = ConfigManager(path).load()

    assert config.provider == ProviderName.OLLAMA
    assert config.default_model == "qwen2.5-coder:14b"
    assert config.providers["ollama"].endpoint == "http://localhost:11434"


def test_set_default_model_persists_config(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    manager = ConfigManager(path)

    manager.set_default_model("qwen2.5-coder:14b")

    assert "default_model: qwen2.5-coder:14b" in path.read_text(encoding="utf-8")
