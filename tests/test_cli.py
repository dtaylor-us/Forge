"""CLI tests."""

from __future__ import annotations

from typer.testing import CliRunner

from forge.cli.app import app
from forge.models.manager import ModelNotFoundError
from forge.models.types import ModelInfo, ModelResponse

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


class FakeModelManager:
    def __init__(self) -> None:
        self.prompts: list[tuple[str, str | None]] = []

    def ask(self, prompt: str, model: str | None = None) -> ModelResponse:
        self.prompts.append((prompt, model))
        return ModelResponse(
            content=f"{model or 'default'}: {prompt}",
            model=model or "default",
            provider="ollama",
        )

    def use_model(self, model: str):
        return type("Config", (), {"default_model": model})()


def test_ask_command_uses_model_override(monkeypatch) -> None:
    manager = FakeModelManager()
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: manager)

    result = runner.invoke(app, ["ask", "--model", "qwen2.5-coder:32b", "Hello"])

    assert result.exit_code == 0
    assert "qwen2.5-coder:32b: Hello" in result.stdout
    assert manager.prompts == [("Hello", "qwen2.5-coder:32b")]


def test_ask_command_reports_missing_model(monkeypatch) -> None:
    def failing_manager() -> object:
        class Manager:
            def ask(self, prompt: str, model: str | None = None) -> ModelResponse:
                raise ModelNotFoundError(
                    "qwen2.5-coder:13b",
                    [ModelInfo(name="qwen2.5-coder:14b", provider="ollama")],
                )

        return Manager()

    monkeypatch.setattr("forge.cli.app._model_manager", failing_manager)

    result = runner.invoke(app, ["ask", "Hello"])

    assert result.exit_code == 1
    assert "qwen2.5-coder:13b" in result.stdout
    assert "forge models" in result.stdout
    assert "qwen2.5-coder:14b" in result.stdout
