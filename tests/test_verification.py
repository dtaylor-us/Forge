"""Verification strategy detection tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from forge.artifacts import ArtifactRegistry, ArtifactType
from forge.cli.app import app
from forge.services import verification_service
from forge.verification.artifact import register_report
from forge.verification.detector import detect_verification_strategy
from forge.verification.executor import VerificationExecutor
from forge.verification.runner import CommandResult

runner = CliRunner()


def _commands(tmp_path: Path) -> list[str]:
    return [step.command for step in detect_verification_strategy(tmp_path).steps]


def test_python_strategy_detection_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")

    strategy = detect_verification_strategy(tmp_path)

    assert strategy.ecosystem == "python"
    assert strategy.package_manager == "pip"
    assert strategy.confidence == "medium"


def test_python_pytest_detection(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    assert "pytest" in _commands(tmp_path)


def test_python_ruff_and_black_detection(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff]\nline-length = 100\n[tool.black]\nline-length = 100\n",
        encoding="utf-8",
    )

    assert "ruff check ." in _commands(tmp_path)
    assert "black --check ." in _commands(tmp_path)


def test_npm_detection_from_package_lock(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {}}', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")

    strategy = detect_verification_strategy(tmp_path)

    assert strategy.ecosystem == "node"
    assert strategy.package_manager == "npm"


def test_pnpm_detection_from_lockfile(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {}}', encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    assert detect_verification_strategy(tmp_path).package_manager == "pnpm"


def test_yarn_detection_from_lockfile(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {}}', encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")

    assert detect_verification_strategy(tmp_path).package_manager == "yarn"


def test_node_scripts_detection_from_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"build": "vite build", "test": "vitest", "lint": "eslint ."}}),
        encoding="utf-8",
    )

    assert _commands(tmp_path) == ["npm run build", "npm test", "npm run lint"]


def test_maven_wrapper_detection(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project />\n", encoding="utf-8")
    (tmp_path / "mvnw").write_text("#!/bin/sh\n", encoding="utf-8")

    assert _commands(tmp_path) == ["./mvnw verify"]


def test_maven_fallback_detection(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project />\n", encoding="utf-8")

    assert _commands(tmp_path) == ["mvn verify"]


def test_gradle_wrapper_detection(tmp_path: Path) -> None:
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    (tmp_path / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")

    assert _commands(tmp_path) == ["./gradlew build"]


def test_go_detection(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example\n", encoding="utf-8")

    assert _commands(tmp_path) == ["go test ./..."]


def test_rust_detection(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'example'\n", encoding="utf-8")

    assert _commands(tmp_path) == ["cargo test", "cargo clippy", "cargo fmt --check"]


def test_dotnet_solution_and_project_detection(tmp_path: Path) -> None:
    (tmp_path / "Example.sln").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Example.csproj").write_text("<Project />\n", encoding="utf-8")

    strategy = detect_verification_strategy(tmp_path)

    assert strategy.ecosystem == "dotnet"
    assert _commands(tmp_path) == ["dotnet build", "dotnet test"]


def test_unknown_repository_detection(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")

    strategy = detect_verification_strategy(tmp_path)

    assert strategy.ecosystem == "unknown"
    assert strategy.steps == []


def test_json_cli_output(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")

    result = runner.invoke(app, ["verify", "--detect", "--json", "--root", str(tmp_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["executed"] is False
    assert payload["strategy"]["ecosystem"] == "python"
    assert payload["strategy"]["steps"][0]["command"] == "ruff check ."


def test_service_returns_structured_strategy_without_executing_commands(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest"}}', encoding="utf-8")

    def fail_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("verification detection must not execute subprocesses")

    monkeypatch.setattr(subprocess, "run", fail_run)

    result = verification_service.detect(tmp_path)

    assert result["executed"] is False
    assert result["strategy"]["steps"][0]["command"] == "npm test"


class FakeRunner:
    def __init__(self, outcomes: dict[str, int | str]) -> None:
        self.outcomes = outcomes
        self.commands: list[str] = []

    def run(self, command: str, working_directory: Path, *, timeout: float) -> CommandResult:
        self.commands.append(command)
        outcome = self.outcomes.get(command, 0)
        if outcome == "timeout":
            return _command_result(command, working_directory, None, timed_out=True)
        if outcome == "exception":
            return _command_result(
                command,
                working_directory,
                None,
                exception="FileNotFoundError: no",
            )
        return _command_result(command, working_directory, int(outcome))


def _command_result(
    command: str,
    working_directory: Path,
    exit_code: int | None,
    *,
    timed_out: bool = False,
    exception: str | None = None,
) -> CommandResult:
    return CommandResult(
        command=command,
        working_directory=working_directory,
        started_at="2026-06-28T00:00:00+00:00",
        completed_at="2026-06-28T00:00:01+00:00",
        duration=1.0,
        exit_code=exit_code,
        stdout="ok" if exit_code == 0 else "",
        stderr="failed" if exit_code not in (0, None) else "",
        timed_out=timed_out,
        exception=exception,
    )


def _execute_with_fake_runner(
    tmp_path: Path,
    outcomes: dict[str, int | str],
    *,
    metadata: dict[str, str | None] | None = None,
) -> tuple[dict[str, Any], FakeRunner]:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff]\n[tool.black]\n[tool.pytest.ini_options]\n",
        encoding="utf-8",
    )
    fake = FakeRunner(outcomes)
    report = VerificationExecutor(fake).execute(tmp_path, timeout=3, metadata=metadata)
    return report.to_dict(), fake


def test_successful_execution(tmp_path: Path) -> None:
    report, fake = _execute_with_fake_runner(tmp_path, {})

    assert report["overall_status"] == "pass"
    assert report["summary"]["counts"]["passed"] == 3
    assert fake.commands == ["black --check .", "ruff check .", "pytest"]


def test_formatter_failure_continues_to_linter_and_tests(tmp_path: Path) -> None:
    """Regression for the I-11 dogfood finding: black is a soft/non-required gate.

    A black --check failure (often caused by tool-version/target-version
    drift rather than an actual formatting problem) must not fail overall
    verification on its own, as long as the required gates (linter, tests)
    pass.
    """
    report, fake = _execute_with_fake_runner(tmp_path, {"black --check .": 1})

    assert report["overall_status"] == "pass"
    assert report["summary"]["by_kind"]["formatter"] == "fail"
    assert report["steps"][0]["required"] is False
    assert fake.commands == ["black --check .", "ruff check .", "pytest"]


def test_formatter_failure_combined_with_linter_failure_still_fails(tmp_path: Path) -> None:
    """A required gate failing alongside the soft formatter gate still fails overall."""
    report, _fake = _execute_with_fake_runner(
        tmp_path, {"black --check .": 1, "ruff check .": 1}
    )

    assert report["overall_status"] == "fail"
    assert report["summary"]["by_kind"]["formatter"] == "fail"
    assert report["summary"]["by_kind"]["linter"] == "fail"


def test_linter_failure(tmp_path: Path) -> None:
    report, _fake = _execute_with_fake_runner(tmp_path, {"ruff check .": 1})

    assert report["overall_status"] == "fail"
    assert report["summary"]["by_kind"]["linter"] == "fail"


def test_build_failure(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"build": "vite build"}}', encoding="utf-8")
    fake = FakeRunner({"npm run build": 1})
    report = VerificationExecutor(fake).execute(tmp_path).to_dict()

    assert report["overall_status"] == "fail"
    assert report["summary"]["by_kind"]["build"] == "fail"


def test_test_failure(tmp_path: Path) -> None:
    report, _fake = _execute_with_fake_runner(tmp_path, {"pytest": 1})

    assert report["overall_status"] == "fail"
    assert report["summary"]["by_kind"]["tests"] == "fail"


def test_timeout_is_recorded_and_execution_continues(tmp_path: Path) -> None:
    report, fake = _execute_with_fake_runner(tmp_path, {"ruff check .": "timeout"})

    assert report["overall_status"] == "fail"
    assert report["summary"]["counts"]["timed_out"] == 1
    assert report["steps"][1]["timed_out"] is True
    assert fake.commands[-1] == "pytest"


def test_missing_executable_is_recorded_as_step_error(tmp_path: Path) -> None:
    report, _fake = _execute_with_fake_runner(tmp_path, {"pytest": "exception"})

    assert report["overall_status"] == "fail"
    assert report["summary"]["counts"]["errors"] == 1
    assert report["steps"][2]["status"] == "error"


def test_unknown_repository_execution_returns_failed_report(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")

    report = VerificationExecutor(FakeRunner({})).execute(tmp_path).to_dict()

    assert report["overall_status"] == "fail"
    assert report["summary"]["reason"] == "No deterministic verification steps were detected."


def test_report_artifact_registration(tmp_path: Path) -> None:
    report, _fake = _execute_with_fake_runner(
        tmp_path,
        {},
        metadata={"workset": "auth", "plan": "auth-plan", "patch": "auth.patch"},
    )
    saved = register_report(
        tmp_path,
        VerificationExecutor(FakeRunner({})).execute(
            tmp_path,
            metadata={"workset": "auth", "plan": "auth-plan", "patch": "auth.patch"},
        ),
    )

    path = Path(saved.to_dict()["artifact"]["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    artifacts = ArtifactRegistry(tmp_path).by_type(ArtifactType.verification)

    assert report["metadata"]["workset"] == "auth"
    assert payload["overall_status"] == "pass"
    assert artifacts[0].metadata["overall_status"] == "pass"
    assert artifacts[0].workset_name == "auth"


def test_verification_cli_json_output(monkeypatch, tmp_path: Path) -> None:
    def fake_run(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "repository": {"root": str(tmp_path), "name": "example"},
            "strategy": {"ecosystem": "python", "steps": [], "confidence": "high"},
            "steps": [],
            "summary": {},
            "artifact": {"path": str(tmp_path / ".forge" / "verifications" / "x.json")},
            "duration": 0.0,
            "overall_status": "pass",
        }

    monkeypatch.setattr("forge.cli.app.verification_service.run", fake_run)

    result = runner.invoke(app, ["verify", "--json", "--root", str(tmp_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "pass"


def test_verification_cli_exit_code_for_failed_report(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "forge.cli.app.verification_service.run",
        lambda *args, **kwargs: {"overall_status": "fail", "repository": {"name": "example"}},
    )

    result = runner.invoke(app, ["verify", "--root", str(tmp_path)])

    assert result.exit_code == 1


def test_verification_cli_exit_code_for_infrastructure_error(monkeypatch, tmp_path: Path) -> None:
    def fail_run(*args: object, **kwargs: object) -> dict[str, object]:
        raise verification_service.VerificationServiceError("boom")

    monkeypatch.setattr("forge.cli.app.verification_service.run", fail_run)

    result = runner.invoke(app, ["verify", "--root", str(tmp_path)])

    assert result.exit_code == 2
