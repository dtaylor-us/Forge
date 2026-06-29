"""Tests for forge implement patch generation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from forge.cli.app import app
from forge.execution import ExecutionService
from forge.execution.execution_prompt import build_implementation_prompt
from forge.models.errors import ModelProviderError
from forge.models.types import ModelResponse
from forge.planning.planner import ImplementationPlan
from forge.services.implementation_service import ImplementationService
from forge.worksets.store import save

runner = CliRunner()

TASK = "Add greeting"
WORKSET = "greeting"

VALID_DIFF = """diff --git a/forge/example.py b/forge/example.py
index 1111111..2222222 100644
--- a/forge/example.py
+++ b/forge/example.py
@@ -1 +1 @@
-print("old")
+print("new")
"""


class FakeModelManager:
    def __init__(self, content: str = VALID_DIFF, *, fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.prompts: list[tuple[str, str | None, int | None]] = []

    def config(self):
        return SimpleNamespace(default_model="fake-model")

    def ask(
        self,
        prompt: str,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> ModelResponse:
        self.prompts.append((prompt, model, timeout_seconds))
        if self.fail:
            raise ModelProviderError("provider unavailable")
        return ModelResponse(
            content=self.content,
            model=model or "fake-model",
            provider="fake",
        )


def _make_workset(root: Path) -> Path:
    source = root / "forge" / "example.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('print("old")\n', encoding="utf-8")
    save(
        root,
        {
            "schema_version": 1,
            "name": WORKSET,
            "query": "greeting example",
            "root": str(root),
            "created_at": "2026-06-28T00:00:00+00:00",
            "updated_at": "2026-06-28T00:00:00+00:00",
            "include_tests": False,
            "max_results": 10,
            "files": [
                {
                    "path": "forge/example.py",
                    "score": 20,
                    "category": "source",
                    "reasons": [{"signal": "filename", "detail": "example", "points": 20}],
                    "manual": False,
                }
            ],
        },
    )
    return source


def test_implementation_prompt_requires_unified_diff_only(tmp_path: Path) -> None:
    _make_workset(tmp_path)
    manager = FakeModelManager()
    plan = ImplementationPlan(
        task=TASK,
        workset_name=WORKSET,
        model="fake-model",
        generated_at=datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC),
        content="Update forge/example.py.",
    )
    request = ExecutionService(manager).create_request(
        tmp_path,
        TASK,
        WORKSET,
        implementation_plan=plan,
    )

    prompt = build_implementation_prompt(
        TASK,
        request.context_bundle,
        request.implementation_plan,
        request.selected_model,
        request.related_memory,
    )

    assert "Return only a raw unified diff" in prompt
    assert "No Markdown fences" in prompt
    assert "No explanations" in prompt
    assert "Prefer files from the workset" in prompt
    assert "Include valid hunk markers" in prompt
    assert "Use paths relative to the repository root" in prompt


def test_valid_model_diff_is_saved_as_patch(tmp_path: Path) -> None:
    _make_workset(tmp_path)
    manager = FakeModelManager()
    result = ImplementationService(manager).implement(tmp_path, TASK, WORKSET)

    assert result.valid is True
    assert result.status == "accepted"
    assert result.patch_path.parent == tmp_path / ".forge" / "patches"
    assert result.affected_files == ["forge/example.py"]
    assert result.patch_path.read_text(encoding="utf-8") == VALID_DIFF
    assert len(manager.prompts) == 1


def test_invalid_model_response_is_saved_under_invalid_patches(tmp_path: Path) -> None:
    _make_workset(tmp_path)
    result = ImplementationService(FakeModelManager("This is not a diff.")).implement(
        tmp_path,
        TASK,
        WORKSET,
    )

    assert result.valid is False
    assert result.status == "rejected"
    assert result.patch_path is None
    assert result.raw_response_path.parent == tmp_path / ".forge" / "patches" / "invalid"
    assert result.validation_errors
    assert result.raw_response_path.read_text(encoding="utf-8") == "This is not a diff.\n"


def test_output_writes_to_explicit_path(tmp_path: Path) -> None:
    _make_workset(tmp_path)
    output = tmp_path / "review" / "change.patch"

    result = ImplementationService(FakeModelManager()).implement(
        tmp_path,
        TASK,
        WORKSET,
        output_path=output,
    )

    assert result.valid is True
    assert result.patch_path == output
    assert output.read_text(encoding="utf-8") == VALID_DIFF


def test_cli_json_output_includes_patch_metadata(monkeypatch, tmp_path: Path) -> None:
    _make_workset(tmp_path)
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: FakeModelManager())

    result = runner.invoke(
        app,
        ["implement", TASK, "--workset", WORKSET, "--root", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["task"] == TASK
    assert data["workset"] == WORKSET
    assert data["model"] == "fake-model"
    assert data["status"] == "accepted"
    assert data["valid"] is True
    assert data["affected_files"] == ["forge/example.py"]
    assert data["patch_name"].endswith(".patch")
    assert data["raw_response_path"] is None
    assert data["next_command"].startswith("forge patch show ")


def test_cli_invalid_model_output_exits_nonzero_and_reports_raw_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_workset(tmp_path)
    monkeypatch.setattr(
        "forge.cli.app._model_manager",
        lambda: FakeModelManager("Here is a change summary, not a patch."),
    )

    result = runner.invoke(
        app,
        ["implement", TASK, "--workset", WORKSET, "--root", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Status: rejected" in result.output
    assert "Invalid artifact path:" in result.output
    assert "No patch was accepted." in result.output


def test_cli_json_invalid_model_output_includes_raw_response_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_workset(tmp_path)
    monkeypatch.setattr(
        "forge.cli.app._model_manager",
        lambda: FakeModelManager("Here is a change summary, not a patch."),
    )

    result = runner.invoke(
        app,
        ["implement", TASK, "--workset", WORKSET, "--root", str(tmp_path), "--json"],
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "rejected"
    assert data["valid"] is False
    assert data["patch_path"] is None
    assert data["patch_name"] is None
    assert data["raw_response_path"].endswith(".txt")
    assert data["next_command"] is None


def test_no_repository_source_files_are_modified(tmp_path: Path) -> None:
    source = _make_workset(tmp_path)
    before = source.read_text(encoding="utf-8")

    result = ImplementationService(FakeModelManager()).implement(tmp_path, TASK, WORKSET)

    assert result.valid is True
    assert source.read_text(encoding="utf-8") == before


def test_provider_failure_exits_cleanly(monkeypatch, tmp_path: Path) -> None:
    _make_workset(tmp_path)
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: FakeModelManager(fail=True))

    result = runner.invoke(
        app,
        ["implement", TASK, "--workset", WORKSET, "--root", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Provider error:" in result.output
    assert "provider unavailable" in result.output


def test_missing_workset_exits_cleanly(monkeypatch, tmp_path: Path) -> None:
    manager = FakeModelManager()
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: manager)

    result = runner.invoke(
        app,
        ["implement", TASK, "--workset", "missing", "--root", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Execution error:" in result.output
    assert "missing" in result.output
    assert manager.prompts == []


def test_existing_patch_commands_work_with_generated_patches(monkeypatch, tmp_path: Path) -> None:
    _make_workset(tmp_path)
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: FakeModelManager())
    implement = runner.invoke(
        app,
        ["implement", TASK, "--workset", WORKSET, "--root", str(tmp_path), "--json"],
    )
    patch_name = json.loads(implement.output)["patch_name"]

    listed = runner.invoke(app, ["patch", "list", "--root", str(tmp_path), "--json"])
    shown = runner.invoke(app, ["patch", "show", patch_name, "--root", str(tmp_path)])
    validated = runner.invoke(app, ["patch", "validate", patch_name, "--root", str(tmp_path)])

    assert listed.exit_code == 0
    assert json.loads(listed.output)[0]["name"] == patch_name
    assert shown.exit_code == 0
    assert "diff --git a/forge/example.py b/forge/example.py" in shown.output
    assert validated.exit_code == 0
    assert "valid" in validated.output
