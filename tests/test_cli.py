"""CLI tests."""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from forge.cli.app import app
from forge.commands.doctor import CheckResult
from forge.config.settings import ProviderName
from forge.models.errors import ModelProviderError
from forge.models.manager import ModelNotFoundError
from forge.models.types import ModelInfo, ModelResponse

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_doctor_command_smoke(monkeypatch) -> None:
    monkeypatch.setattr(
        "forge.cli.app.run_doctor",
        lambda config: [CheckResult("Python >= 3.12", True, "3.12.0")],
    )
    monkeypatch.setattr(
        "forge.cli.app._config_manager",
        lambda: SimpleNamespace(load=lambda: SimpleNamespace()),
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Forge Doctor" in result.stdout
    assert "Python >= 3.12" in result.stdout


def test_models_command_smoke(monkeypatch) -> None:
    class Manager:
        def config(self):
            return SimpleNamespace(provider=ProviderName.OLLAMA, default_model="llama3.1:8b")

        def list_models(self) -> list[ModelInfo]:
            return [ModelInfo(name="llama3.1:8b", provider="ollama", details="4.7 GB")]

    monkeypatch.setattr("forge.cli.app._model_manager", lambda: Manager())

    result = runner.invoke(app, ["models"])

    assert result.exit_code == 0
    assert "Forge Models (ollama)" in result.stdout
    assert "llama3.1:8b" in result.stdout


def test_ask_help_smoke() -> None:
    result = runner.invoke(app, ["ask", "--help"])

    assert result.exit_code == 0
    assert "Prompt to send to the configured model" in result.stdout
    assert "--timeout" in result.stdout


def test_config_show_smoke(monkeypatch) -> None:
    monkeypatch.setattr(
        "forge.cli.app._config_manager",
        lambda: SimpleNamespace(show=lambda: "provider: ollama\n"),
    )

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert "provider: ollama" in result.stdout


class FakeModelManager:
    def __init__(self) -> None:
        self.prompts: list[tuple[str, str | None, int | None]] = []

    def ask(
        self,
        prompt: str,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> ModelResponse:
        self.prompts.append((prompt, model, timeout_seconds))
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
    assert manager.prompts == [("Hello", "qwen2.5-coder:32b", None)]


def test_ask_command_uses_timeout_override(monkeypatch) -> None:
    manager = FakeModelManager()
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: manager)

    result = runner.invoke(app, ["ask", "--timeout", "240", "Hello"])

    assert result.exit_code == 0
    assert manager.prompts == [("Hello", None, 240)]


def test_config_set_default_model_smoke(monkeypatch) -> None:
    manager = FakeModelManager()
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: manager)

    result = runner.invoke(app, ["config", "set-default-model", "llama3.1:8b"])

    assert result.exit_code == 0
    assert "Default model set to llama3.1:8b" in result.stdout


def test_ask_command_reports_missing_model(monkeypatch) -> None:
    def failing_manager() -> object:
        class Manager:
            def ask(
                self,
                prompt: str,
                model: str | None = None,
                timeout_seconds: int | None = None,
            ) -> ModelResponse:
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


def test_ask_command_formats_provider_errors(monkeypatch) -> None:
    def failing_manager() -> object:
        class Manager:
            def ask(
                self,
                prompt: str,
                model: str | None = None,
                timeout_seconds: int | None = None,
            ) -> ModelResponse:
                raise ModelProviderError("Unable to reach Ollama at http://localhost:11434")

        return Manager()

    monkeypatch.setattr("forge.cli.app._model_manager", failing_manager)

    result = runner.invoke(app, ["ask", "Hello"])

    assert result.exit_code == 1
    assert "Provider error:" in result.stdout
    assert "Unable to reach Ollama" in result.stdout


def test_ask_command_sends_literal_prompt_without_project_context(monkeypatch, tmp_path) -> None:
    manager = FakeModelManager()
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: manager)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Existing project context\n", encoding="utf-8")

    result = runner.invoke(app, ["ask", "Explain this project"])

    assert result.exit_code == 0
    assert manager.prompts == [("Explain this project", None, None)]


def test_explain_project_sends_explicit_project_context(monkeypatch, tmp_path) -> None:
    manager = FakeModelManager()
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: manager)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")

    result = runner.invoke(app, ["explain-project", "--timeout", "180"])

    assert result.exit_code == 0
    prompt, model, timeout_seconds = manager.prompts[0]
    assert model is None
    assert timeout_seconds == 180
    assert "Compact tree:" in prompt
    assert "File: README.md" in prompt
    assert "File: pyproject.toml" in prompt
    assert ".git" not in prompt


def test_repo_tree_command(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")

    result = runner.invoke(app, ["repo", "tree", "--root", str(tmp_path), "--max-depth", "1"])

    assert result.exit_code == 0
    assert "[D]" in result.stdout
    assert "src/" in result.stdout


def test_repo_detect_command(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")

    result = runner.invoke(app, ["repo", "detect", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "Repository Detection" in result.stdout
    assert "Python" in result.stdout


def test_repo_grep_command(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("forge.repository.grep.shutil.which", lambda _: None)
    (tmp_path / "forge").mkdir()
    (tmp_path / "forge" / "models.py").write_text(
        "class ModelManager:\n    pass\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["repo", "grep", "ModelManager", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "Repository Search" in result.stdout
    assert "forge/models.py" in result.stdout
    assert "ModelManager" in result.stdout


def test_repo_files_command(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.java").write_text("class App {}\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")

    result = runner.invoke(app, ["repo", "files", "--root", str(tmp_path), "--ext", "java"])

    assert result.exit_code == 0
    assert "Repository Files" in result.stdout
    assert "src/App.java" in result.stdout
    assert "README.md" not in result.stdout
