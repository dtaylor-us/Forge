"""Model manager tests."""

from __future__ import annotations

import pytest

from forge.config.manager import ConfigManager
from forge.models import manager as manager_module
from forge.models.errors import ModelProviderError
from forge.models.manager import ModelManager, ModelNotFoundError
from forge.models.types import ModelInfo, ModelResponse


class FakeProvider:
    name = "ollama"
    endpoint = "http://localhost:11434"

    def __init__(self) -> None:
        self.asked_with: tuple[str, str] | None = None
        self.timeout_seconds: int | None = None

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(name="qwen2.5-coder:14b", provider=self.name),
            ModelInfo(name="qwen2.5-coder:32b", provider=self.name),
            ModelInfo(name="llama3.1:8b", provider=self.name),
        ]

    def ask(
        self,
        prompt: str,
        model: str,
        timeout_seconds: int | None = None,
    ) -> ModelResponse:
        self.asked_with = (prompt, model)
        self.timeout_seconds = timeout_seconds
        return ModelResponse(content="hello", model=model, provider=self.name)

    def normalize_model_name(self, model: str) -> str:
        return model


class FailingProvider(FakeProvider):
    def ask(
        self,
        prompt: str,
        model: str,
        timeout_seconds: int | None = None,
    ) -> ModelResponse:
        raise ModelProviderError("boom")


class MissingDefaultProvider(FakeProvider):
    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name="qwen2.5-coder:14b", provider=self.name)]


class TaggedOnlyProvider(FakeProvider):
    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name="llama3.1:8b", provider=self.name)]


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))

    def error(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


def test_ask_uses_configured_default_model(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
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
    provider = FakeProvider()
    manager = ModelManager(ConfigManager(config_path))
    monkeypatch.setattr(manager, "_provider", lambda config, timeout_seconds=None: provider)

    response = manager.ask("Hello")

    assert response.model == "qwen2.5-coder:14b"
    assert provider.asked_with == ("Hello", "qwen2.5-coder:14b")


def test_ask_model_override_wins_over_default(tmp_path, monkeypatch) -> None:
    provider = FakeProvider()
    manager = ModelManager(ConfigManager(tmp_path / "config.yaml"))
    monkeypatch.setattr(manager, "_provider", lambda config, timeout_seconds=None: provider)

    response = manager.ask("Hello", model="qwen2.5-coder:32b")

    assert response.model == "qwen2.5-coder:32b"
    assert provider.asked_with == ("Hello", "qwen2.5-coder:32b")


def test_ask_forwards_timeout_override(tmp_path, monkeypatch) -> None:
    provider = FakeProvider()
    manager = ModelManager(ConfigManager(tmp_path / "config.yaml"))
    monkeypatch.setattr(manager, "_provider", lambda config, timeout_seconds=None: provider)

    manager.ask("Hello", model="qwen2.5-coder:14b", timeout_seconds=240)

    assert provider.timeout_seconds == 240


def test_ask_does_not_use_nonexistent_default_model(tmp_path, monkeypatch) -> None:
    provider = MissingDefaultProvider()
    manager = ModelManager(ConfigManager(tmp_path / "config.yaml"))
    monkeypatch.setattr(manager, "_provider", lambda config, timeout_seconds=None: provider)

    with pytest.raises(ModelNotFoundError) as exc_info:
        manager.ask("Hello")

    assert exc_info.value.requested_model == "llama3.1:8b"
    assert provider.asked_with is None


def test_untagged_model_name_is_not_silently_resolved_to_tagged_model(
    tmp_path, monkeypatch
) -> None:
    provider = TaggedOnlyProvider()
    manager = ModelManager(ConfigManager(tmp_path / "config.yaml"))
    monkeypatch.setattr(manager, "_provider", lambda config, timeout_seconds=None: provider)

    with pytest.raises(ModelNotFoundError) as exc_info:
        manager.ask("Hello", model="llama3.1")

    assert exc_info.value.requested_model == "llama3.1"
    assert [model.name for model in exc_info.value.suggestions] == ["llama3.1:8b"]
    assert provider.asked_with is None


def test_use_model_validates_and_persists(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    manager = ModelManager(ConfigManager(config_path))
    monkeypatch.setattr(
        manager,
        "_provider",
        lambda config, timeout_seconds=None: FakeProvider(),
    )

    manager.use_model("qwen2.5-coder:14b")

    assert "default_model: qwen2.5-coder:14b" in config_path.read_text(encoding="utf-8")


def test_validate_model_reports_close_matches(tmp_path, monkeypatch) -> None:
    manager = ModelManager(ConfigManager(tmp_path / "config.yaml"))
    monkeypatch.setattr(
        manager,
        "_provider",
        lambda config, timeout_seconds=None: FakeProvider(),
    )

    with pytest.raises(ModelNotFoundError) as exc_info:
        manager.validate_model("qwen2.5-coder:13b")

    assert exc_info.value.requested_model == "qwen2.5-coder:13b"
    assert "qwen2.5-coder:14b" in [model.name for model in exc_info.value.suggestions]


def test_ask_logs_metrics_without_prompt_or_response(tmp_path, monkeypatch) -> None:
    logger = FakeLogger()
    provider = FakeProvider()
    manager = ModelManager(ConfigManager(tmp_path / "config.yaml"))
    monkeypatch.setattr(manager, "_provider", lambda config, timeout_seconds=None: provider)
    monkeypatch.setattr(manager_module, "logger", logger)

    manager.ask("sensitive prompt", model="qwen2.5-coder:14b")

    assert [event for event, _ in logger.events] == [
        "models.ask.start",
        "models.ask.complete",
    ]
    complete = logger.events[1][1]
    assert complete["provider"] == "ollama"
    assert complete["endpoint"] == "http://localhost:11434"
    assert complete["model"] == "qwen2.5-coder:14b"
    assert complete["prompt_size"] == len("sensitive prompt")
    assert complete["response_size"] == len("hello")
    assert "sensitive prompt" not in str(logger.events)
    assert "hello" not in str(logger.events)
