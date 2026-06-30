"""Tests for Phase 2G: workset-based implementation planning."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from forge.cli.app import app
from forge.context.bundle import ContextBundle, ContextBundleFile
from forge.models.types import ModelResponse
from forge.planning.planner import ImplementationPlan, PlannerError, generate_plan
from forge.planning.prompts import build_planning_prompt
from forge.planning.render import render_plan_json, render_plan_text
from forge.planning.store import plans_dir, save_plan
from forge.worksets.store import save

runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TASK = "Add timeout validation"
WORKSET_NAME = "model-config"


def _make_bundle(workset_name: str = WORKSET_NAME, files: list | None = None) -> ContextBundle:
    bundle = ContextBundle(
        workset_name=workset_name,
        query="model manager config",
        root="/repo",
        generated_at="2026-06-28T00:00:00+00:00",
    )
    if files:
        bundle.files = files
        bundle.total_chars = sum(f.char_count for f in files)
        bundle.total_tokens = sum(f.token_estimate for f in files)
    else:
        f = ContextBundleFile(
            path="forge/models/manager.py",
            category="source",
            score=15,
            line_count=80,
            char_count=2000,
            token_estimate=500,
            summary=["Manages model selection", "Validates provider config"],
            symbols=["ModelManager", "ask", "validate_model"],
            dependency_hints=["imports forge.models.base"],
            excerpts=["class ModelManager:\n    def ask(self, prompt):"],
        )
        bundle.files = [f]
        bundle.total_chars = f.char_count
        bundle.total_tokens = f.token_estimate
    return bundle


def _make_workset(tmp_path: Path, name: str = WORKSET_NAME) -> None:
    data = {
        "schema_version": 1,
        "name": name,
        "query": "model manager config",
        "root": str(tmp_path),
        "created_at": "2026-06-28T00:00:00+00:00",
        "updated_at": "2026-06-28T00:00:00+00:00",
        "include_tests": False,
        "max_results": 10,
        "files": [
            {
                "path": "forge/models/manager.py",
                "score": 15,
                "category": "source",
                "reasons": [{"signal": "filename", "detail": "manager", "points": 15}],
                "manual": False,
            }
        ],
    }
    save(tmp_path, data)
    src = tmp_path / "forge" / "models" / "manager.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("class ModelManager:\n    def ask(self): pass\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------


def test_prompt_includes_task():
    bundle = _make_bundle()
    prompt = build_planning_prompt(TASK, bundle, "ollama/qwen2.5")
    assert TASK in prompt


def test_prompt_includes_workset_name():
    bundle = _make_bundle()
    prompt = build_planning_prompt(TASK, bundle, "ollama/qwen2.5")
    assert WORKSET_NAME in prompt


def test_prompt_includes_file_summaries():
    bundle = _make_bundle()
    prompt = build_planning_prompt(TASK, bundle, "ollama/qwen2.5")
    assert "Manages model selection" in prompt


def test_prompt_includes_relevant_excerpts():
    bundle = _make_bundle()
    prompt = build_planning_prompt(TASK, bundle, "ollama/qwen2.5")
    assert "ModelManager" in prompt


def test_prompt_instructs_no_file_modification():
    bundle = _make_bundle()
    prompt = build_planning_prompt(TASK, bundle, "ollama/qwen2.5")
    assert "Do NOT generate code patches" in prompt
    assert "Do NOT modify any files" in prompt


def test_prompt_includes_model_name():
    bundle = _make_bundle()
    model = "qwen2.5-coder:14b"
    prompt = build_planning_prompt(TASK, bundle, model)
    assert model in prompt


# ---------------------------------------------------------------------------
# Planner tests
# ---------------------------------------------------------------------------


def _mock_response(content: str = "# Forge Implementation Plan\n\n## Task\nDone") -> ModelResponse:
    return ModelResponse(
        content=content,
        model="qwen2.5",
        provider="ollama",
    )


def test_planner_calls_model_manager(tmp_path):
    _make_workset(tmp_path)
    mock_manager = MagicMock()
    mock_manager.config.return_value = MagicMock(default_model="qwen2.5")
    mock_manager.ask.return_value = _mock_response()

    result = generate_plan(tmp_path, TASK, WORKSET_NAME, model_manager=mock_manager)

    assert mock_manager.ask.called
    assert result.task == TASK
    assert result.workset_name == WORKSET_NAME


def test_planner_uses_model_override(tmp_path):
    _make_workset(tmp_path)
    mock_manager = MagicMock()
    mock_manager.config.return_value = MagicMock(default_model="default-model")
    mock_manager.ask.return_value = _mock_response()

    generate_plan(tmp_path, TASK, WORKSET_NAME, model="custom:7b", model_manager=mock_manager)

    call_kwargs = mock_manager.ask.call_args
    assert call_kwargs.kwargs.get("model") == "custom:7b" or "custom:7b" in str(call_kwargs)


def test_planner_missing_workset_raises(tmp_path):
    mock_manager = MagicMock()
    with pytest.raises(PlannerError, match="not found") as exc_info:
        generate_plan(tmp_path, TASK, "nonexistent", model_manager=mock_manager)
    # Regression for I-06: the message must not duplicate "not found".
    assert str(exc_info.value).lower().count("not found") == 1


def test_planner_model_error_raises(tmp_path):
    from forge.models.errors import ModelProviderError

    _make_workset(tmp_path)
    mock_manager = MagicMock()
    mock_manager.config.return_value = MagicMock(default_model="qwen2.5")
    mock_manager.ask.side_effect = ModelProviderError("connection refused")

    with pytest.raises(PlannerError, match="provider error"):
        generate_plan(tmp_path, TASK, WORKSET_NAME, model_manager=mock_manager)


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------


def test_save_plan_creates_file(tmp_path):
    forge_dir = tmp_path / ".forge"
    plan = ImplementationPlan(
        task=TASK,
        workset_name=WORKSET_NAME,
        model="qwen2.5",
        generated_at=datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC),
        content="# Forge Implementation Plan\n\nDone.",
    )
    dest = save_plan(plan, forge_dir)
    assert dest.exists()
    assert WORKSET_NAME in dest.name
    assert dest.read_text().startswith("# Forge Implementation Plan")


def test_save_plan_under_plans_subdir(tmp_path):
    forge_dir = tmp_path / ".forge"
    plan = ImplementationPlan(
        task=TASK,
        workset_name=WORKSET_NAME,
        model="qwen2.5",
        generated_at=datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC),
        content="content",
    )
    dest = save_plan(plan, forge_dir)
    assert dest.parent == plans_dir(forge_dir)


# ---------------------------------------------------------------------------
# Render tests
# ---------------------------------------------------------------------------


def test_render_plan_text():
    plan = ImplementationPlan(
        task=TASK,
        workset_name=WORKSET_NAME,
        model="qwen2.5",
        generated_at=datetime(2026, 6, 28, tzinfo=UTC),
        content="# Plan\ncontent",
    )
    assert render_plan_text(plan) == "# Plan\ncontent"


def test_render_plan_json():
    plan = ImplementationPlan(
        task=TASK,
        workset_name=WORKSET_NAME,
        model="qwen2.5",
        generated_at=datetime(2026, 6, 28, tzinfo=UTC),
        content="# Plan",
        saved_path=Path("/repo/.forge/plans/model-config-20260628.md"),
    )
    data = json.loads(render_plan_json(plan))
    assert data["task"] == TASK
    assert data["workset_name"] == WORKSET_NAME
    assert data["model"] == "qwen2.5"
    assert data["content"] == "# Plan"
    assert data["saved_path"] is not None


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_plan_missing_workset(tmp_path):
    result = runner.invoke(
        app,
        ["plan", TASK, "--workset", "missing", "--root", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "Planning error" in result.output or "not found" in result.output
    # Regression for I-06: "not found: ... not found." duplication.
    assert result.output.lower().count("not found") == 1


def _cli_mock_manager():
    mock_manager = MagicMock()
    mock_manager.config.return_value = MagicMock(default_model="qwen2.5")
    mock_manager.ask.return_value = _mock_response("# Forge Implementation Plan\n\n## Task\nOK")
    return mock_manager


def test_cli_plan_success(tmp_path):
    _make_workset(tmp_path)
    mock_manager = _cli_mock_manager()
    with patch("forge.cli.app._model_manager", return_value=mock_manager):
        result = runner.invoke(
            app,
            ["plan", TASK, "--workset", WORKSET_NAME, "--root", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "Forge Implementation Plan" in result.output


def test_cli_plan_save(tmp_path):
    _make_workset(tmp_path)
    mock_manager = _cli_mock_manager()
    with patch("forge.cli.app._model_manager", return_value=mock_manager):
        result = runner.invoke(
            app,
            ["plan", TASK, "--workset", WORKSET_NAME, "--root", str(tmp_path), "--save"],
        )
    assert result.exit_code == 0
    assert "Plan saved" in result.output
    plans = list((tmp_path / ".forge" / "plans").glob("*.md"))
    assert len(plans) == 1


def test_cli_plan_json_output(tmp_path):
    _make_workset(tmp_path)
    mock_manager = MagicMock()
    mock_manager.config.return_value = MagicMock(default_model="qwen2.5")
    mock_manager.ask.return_value = _mock_response("# Forge Implementation Plan")
    with patch("forge.cli.app._model_manager", return_value=mock_manager):
        result = runner.invoke(
            app,
            ["plan", TASK, "--workset", WORKSET_NAME, "--root", str(tmp_path), "--json"],
        )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["task"] == TASK
    assert data["workset_name"] == WORKSET_NAME


def test_cli_plan_model_override(tmp_path):
    _make_workset(tmp_path)
    mock_response = _mock_response("# Forge Implementation Plan")
    mock_manager = MagicMock()
    mock_manager.config.return_value = MagicMock(default_model="qwen2.5")
    mock_manager.ask.return_value = mock_response
    with patch("forge.cli.app._model_manager", return_value=mock_manager):
        result = runner.invoke(
            app,
            [
                "plan",
                TASK,
                "--workset",
                WORKSET_NAME,
                "--root",
                str(tmp_path),
                "--model",
                "qwen2.5-coder:14b",
            ],
        )
    assert result.exit_code == 0
    call_kwargs = mock_manager.ask.call_args
    assert call_kwargs is not None
    assert call_kwargs.kwargs.get("model") == "qwen2.5-coder:14b"


# ---------------------------------------------------------------------------
# `forge plan-list` CLI tests
# ---------------------------------------------------------------------------


def test_cli_plan_list_empty(tmp_path):
    result = runner.invoke(app, ["plan-list", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "No saved plans found" in result.output


def test_cli_plan_list_shows_saved_plans(tmp_path):
    _make_workset(tmp_path)
    mock_manager = _cli_mock_manager()
    with patch("forge.cli.app._model_manager", return_value=mock_manager):
        save_result = runner.invoke(
            app,
            ["plan", TASK, "--workset", WORKSET_NAME, "--root", str(tmp_path), "--save"],
        )
    assert save_result.exit_code == 0

    result = runner.invoke(app, ["plan-list", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert WORKSET_NAME in result.output
    assert "Forge Implementation Plan" in result.output


def test_cli_plan_list_json_output(tmp_path):
    _make_workset(tmp_path)
    mock_manager = _cli_mock_manager()
    with patch("forge.cli.app._model_manager", return_value=mock_manager):
        runner.invoke(
            app,
            ["plan", TASK, "--workset", WORKSET_NAME, "--root", str(tmp_path), "--save"],
        )

    result = runner.invoke(app, ["plan-list", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["workset"] == WORKSET_NAME
    assert data[0]["generated_at"] != "-"
    assert "name" in data[0] and "path" in data[0] and "preview" in data[0]


def test_cli_plan_list_does_not_break_plan_command(tmp_path):
    """`forge plan` (positional task arg) and `forge plan-list` must coexist."""
    _make_workset(tmp_path)
    mock_manager = _cli_mock_manager()
    with patch("forge.cli.app._model_manager", return_value=mock_manager):
        plan_result = runner.invoke(
            app,
            ["plan", TASK, "--workset", WORKSET_NAME, "--root", str(tmp_path)],
        )
    assert plan_result.exit_code == 0
    assert "Forge Implementation Plan" in plan_result.output

    list_result = runner.invoke(app, ["plan-list", "--root", str(tmp_path)])
    assert list_result.exit_code == 0
