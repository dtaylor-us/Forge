"""Tests for the Engineering Workflow Engine (Phase 6.0)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from forge.services import workflow_service
from forge.workflows.engine import WorkflowEngine
from forge.workflows.models import (
    WorkflowRun,
    WorkflowStage,
    WorkflowStageStatus,
    WorkflowStatus,
    WorkflowTemplate,
)
from forge.workflows.registry import WorkflowRegistry
from forge.workflows.templates import ALL_DEFINITIONS, FEATURE

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def registry(tmp_root: Path) -> WorkflowRegistry:
    return WorkflowRegistry(tmp_root / ".forge" / "workflows")


def _make_engine(root: Path, registry: WorkflowRegistry, **patches: Any) -> WorkflowEngine:
    return WorkflowEngine(root, registry=registry)


def _mock_services(
    *,
    patch_valid: bool = True,
    verify_status: str = "pass",
    policy_status: str = "pass",
) -> dict[str, MagicMock]:
    """Return a dict of mock service callables for patching."""
    repo_mock = MagicMock(return_value={"root_path": "/repo", "languages": ["python"]})
    workset_create_mock = MagicMock(return_value={"name": "ws", "files": []})
    context_mock = MagicMock(return_value={"file_count": 3, "path": "/tmp/ctx.md"})
    plan_mock = MagicMock(
        return_value={"task": "t", "saved_path": "/tmp/plan.md", "model": "test"}
    )

    impl_result = MagicMock()
    impl_result.valid = patch_valid
    impl_result.patch_path = Path("/tmp/my.patch") if patch_valid else None
    impl_result.patch_name = "my.patch" if patch_valid else None
    impl_result.validation_errors = [] if patch_valid else ["bad patch"]
    impl_result.to_dict.return_value = {
        "patch_name": "my.patch" if patch_valid else None,
        "patch_path": "/tmp/my.patch" if patch_valid else None,
        "affected_files": ["foo.py"],
        "validation_errors": [] if patch_valid else ["bad patch"],
        "valid": patch_valid,
    }
    impl_mock = MagicMock()
    impl_mock.return_value.implement.return_value = impl_result

    validate_mock = MagicMock(
        return_value={
            "valid": patch_valid,
            "structural_valid": patch_valid,
            "apply_check_valid": patch_valid if patch_valid else False,
            "name": "my.patch",
            "validation_errors": [] if patch_valid else ["hunk line count mismatch"],
        }
    )
    verify_mock = MagicMock(
        return_value={"overall_status": verify_status, "summary": {}}
    )
    policy_mock = MagicMock(
        return_value={"patch": "my.patch", "evaluation": {"status": policy_status, "checks": []}}
    )

    from forge.git.service import GitServiceError

    def _apply_check_side_effect(patch_path):  # type: ignore[no-untyped-def]
        if not patch_valid:
            raise GitServiceError("patch fragment without header")

    git_apply_check_mock = MagicMock(side_effect=_apply_check_side_effect)

    return {
        "repo": repo_mock,
        "workset_create": workset_create_mock,
        "context": context_mock,
        "plan": plan_mock,
        "impl_cls": impl_mock,
        "validate": validate_mock,
        "verify": verify_mock,
        "policy": policy_mock,
        "git_apply_check": git_apply_check_mock,
    }


def _patch_all(mocks: dict[str, MagicMock]):
    """Return context managers for all service patches."""
    return [
        patch("forge.services.repository_service.detect", mocks["repo"]),
        patch("forge.services.workset_service.create", mocks["workset_create"]),
        patch("forge.services.workset_service.generate_context", mocks["context"]),
        patch("forge.services.planning_service.generate", mocks["plan"]),
        patch("forge.services.implementation_service.ImplementationService", mocks["impl_cls"]),
        patch("forge.services.patch_service.validate", mocks["validate"]),
        patch("forge.services.verification_service.run", mocks["verify"]),
        patch("forge.services.verification_service.VerificationServiceError", Exception),
        patch("forge.services.policy_service.check", mocks["policy"]),
        patch("forge.patches.service.resolve_patch_path", return_value=Path("/tmp/my.patch")),
        patch("forge.git.service.GitService.apply_check", mocks["git_apply_check"]),
    ]


# ---------------------------------------------------------------------------
# 1. Template definitions
# ---------------------------------------------------------------------------


def test_all_three_templates_defined():
    assert WorkflowTemplate.feature in ALL_DEFINITIONS
    assert WorkflowTemplate.bugfix in ALL_DEFINITIONS
    assert WorkflowTemplate.refactor in ALL_DEFINITIONS


def test_template_stage_names():
    for defn in ALL_DEFINITIONS.values():
        assert "workset" in defn.stage_names
        assert "patch" in defn.stage_names
        assert "policy" in defn.stage_names


def test_template_to_dict():
    d = FEATURE.to_dict()
    assert d["template"] == "feature"
    assert isinstance(d["stages"], list)


# ---------------------------------------------------------------------------
# 2. WorkflowRun model
# ---------------------------------------------------------------------------


def test_workflow_run_to_dict():
    run = WorkflowRun(
        id="abc123",
        template=WorkflowTemplate.feature,
        task="Add button",
        repository="/repo",
    )
    d = run.to_dict()
    assert d["id"] == "abc123"
    assert d["template"] == "feature"
    assert d["status"] == "pending"
    assert d["stages"] == []


def test_workflow_stage_duration():
    from datetime import UTC, datetime, timedelta

    stage = WorkflowStage(name="plan", description="", service="PlanningService")
    stage.started_at = datetime(2024, 1, 1, tzinfo=UTC)
    stage.completed_at = stage.started_at + timedelta(seconds=5)
    assert stage.duration_seconds == 5.0


# ---------------------------------------------------------------------------
# 3. Registry
# ---------------------------------------------------------------------------


def test_registry_save_and_load(tmp_root: Path):
    reg = WorkflowRegistry(tmp_root / "wf")
    run = WorkflowRun(id="r1", template=WorkflowTemplate.feature, task="t", repository="/r")
    path = reg.save(run)
    assert path.exists()
    data = reg.load("r1")
    assert data is not None
    assert data["id"] == "r1"


def test_registry_list_runs(tmp_root: Path):
    reg = WorkflowRegistry(tmp_root / "wf")
    for i, tmpl in enumerate(
        [WorkflowTemplate.feature, WorkflowTemplate.bugfix, WorkflowTemplate.feature]
    ):
        reg.save(WorkflowRun(id=f"r{i}", template=tmpl, task="t", repository="/r"))
    all_runs = reg.list_runs()
    assert len(all_runs) == 3
    feature_runs = reg.list_runs(template=WorkflowTemplate.feature)
    assert len(feature_runs) == 2


def test_registry_load_missing(tmp_root: Path):
    reg = WorkflowRegistry(tmp_root / "wf")
    assert reg.load("nonexistent") is None


def test_workflow_show_full_id(tmp_path: Path) -> None:
    registry = WorkflowRegistry(tmp_path)
    data = {
        "id": "abcd1234efgh5678",
        "template": "feature",
        "status": "completed",
        "task": "test",
        "stages": [],
    }
    (tmp_path / "abcd1234efgh5678.json").write_text(json.dumps(data), encoding="utf-8")

    result = registry.load("abcd1234efgh5678")

    assert result is not None
    assert result["id"] == "abcd1234efgh5678"


def test_workflow_show_unique_prefix(tmp_path: Path) -> None:
    registry = WorkflowRegistry(tmp_path)
    data = {
        "id": "abcd1234efgh5678",
        "template": "feature",
        "status": "completed",
        "task": "test",
        "stages": [],
    }
    (tmp_path / "abcd1234efgh5678.json").write_text(json.dumps(data), encoding="utf-8")

    result = registry.load("abcd1234")

    assert result is not None
    assert result["id"] == "abcd1234efgh5678"


def test_cli_workflow_list_then_show_with_truncated_id(tmp_path: Path) -> None:
    """End-to-end regression for the reported "truncated ID doesn't resolve" issue.

    `forge workflow list` displays only the first 12 characters of a run ID.
    This reproduces that exact flow through the real CLI (not just the
    registry) to confirm the displayed, truncated ID resolves via
    `forge workflow show`.
    """
    from typer.testing import CliRunner

    from forge.cli.app import app

    runner = CliRunner()
    (tmp_path / ".git").mkdir()
    registry = WorkflowRegistry.from_root(tmp_path)
    run = WorkflowRun(
        id="c92605e4899c41b4",
        template=WorkflowTemplate.feature,
        task="add request tracing",
        repository=str(tmp_path),
        status=WorkflowStatus.completed,
    )
    registry.save(run)

    listed = runner.invoke(app, ["workflow", "list", "--root", str(tmp_path), "--json"])
    assert listed.exit_code == 0
    runs = json.loads(listed.output)
    assert runs[0]["id"] == "c92605e4899c41b4"
    truncated_id = runs[0]["id"][:12]
    assert truncated_id == "c92605e4899c"

    shown = runner.invoke(app, ["workflow", "show", truncated_id, "--root", str(tmp_path)])
    assert shown.exit_code == 0
    assert "c92605e4899c41b4" in shown.output
    assert "not found" not in shown.output.lower()


def test_workflow_show_ambiguous_prefix_raises(tmp_path: Path) -> None:
    from forge.workflows.registry import AmbiguousWorkflowIdError

    registry = WorkflowRegistry(tmp_path)
    for run_id in ["abcd1234aaaa0001", "abcd1234bbbb0002"]:
        data = {
            "id": run_id,
            "template": "feature",
            "status": "completed",
            "task": "test",
            "stages": [],
        }
        (tmp_path / f"{run_id}.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(AmbiguousWorkflowIdError) as exc_info:
        registry.load("abcd1234")

    assert "abcd1234" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. Stage ordering
# ---------------------------------------------------------------------------


def test_stage_ordering(tmp_root: Path, registry: WorkflowRegistry):
    mocks = _mock_services()
    engine = WorkflowEngine(tmp_root, registry=registry)
    with (
        patch("forge.services.repository_service.detect", mocks["repo"]),
        patch("forge.services.workset_service.create", mocks["workset_create"]),
        patch("forge.services.workset_service.generate_context", mocks["context"]),
        patch("forge.services.planning_service.generate", mocks["plan"]),
        patch("forge.services.implementation_service.ImplementationService", mocks["impl_cls"]),
        patch("forge.services.patch_service.validate", mocks["validate"]),
        patch("forge.services.verification_service.run", mocks["verify"]),
        patch("forge.services.verification_service.VerificationServiceError", Exception),
        patch("forge.services.policy_service.check", mocks["policy"]),
        patch("forge.patches.service.resolve_patch_path", return_value=Path("/tmp/my.patch")),
        patch("forge.git.service.GitService.apply_check", mocks["git_apply_check"]),
    ):
        run = engine.run(WorkflowTemplate.feature, "add button")

    stage_names = [s.name for s in run.stages]
    assert stage_names == [
        "repository", "workset", "context", "plan", "patch", "validate", "verify", "policy"
    ]


# ---------------------------------------------------------------------------
# 5. Feature / BugFix / Refactor workflows complete successfully
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template",
    [WorkflowTemplate.feature, WorkflowTemplate.bugfix, WorkflowTemplate.refactor],
)
def test_workflow_completes(tmp_root: Path, registry: WorkflowRegistry, template):
    mocks = _mock_services()
    engine = WorkflowEngine(tmp_root, registry=registry)
    with (
        patch("forge.services.repository_service.detect", mocks["repo"]),
        patch("forge.services.workset_service.create", mocks["workset_create"]),
        patch("forge.services.workset_service.generate_context", mocks["context"]),
        patch("forge.services.planning_service.generate", mocks["plan"]),
        patch("forge.services.implementation_service.ImplementationService", mocks["impl_cls"]),
        patch("forge.services.patch_service.validate", mocks["validate"]),
        patch("forge.services.verification_service.run", mocks["verify"]),
        patch("forge.services.verification_service.VerificationServiceError", Exception),
        patch("forge.services.policy_service.check", mocks["policy"]),
        patch("forge.patches.service.resolve_patch_path", return_value=Path("/tmp/my.patch")),
        patch("forge.git.service.GitService.apply_check", mocks["git_apply_check"]),
    ):
        run = engine.run(template, "some task")

    assert run.status == WorkflowStatus.completed
    assert all(s.status == WorkflowStageStatus.completed for s in run.stages)
    assert run.workset_name is not None
    assert run.patch_path is not None


# ---------------------------------------------------------------------------
# 6. Stage failure — stops workflow, preserves prior artifacts
# ---------------------------------------------------------------------------


def test_stage_failure_stops_workflow(tmp_root: Path, registry: WorkflowRegistry):
    mocks = _mock_services()
    mocks["plan"].side_effect = Exception("model unavailable")
    engine = WorkflowEngine(tmp_root, registry=registry)
    with (
        patch("forge.services.repository_service.detect", mocks["repo"]),
        patch("forge.services.workset_service.create", mocks["workset_create"]),
        patch("forge.services.workset_service.generate_context", mocks["context"]),
        patch("forge.services.planning_service.generate", mocks["plan"]),
        patch("forge.services.implementation_service.ImplementationService", mocks["impl_cls"]),
        patch("forge.services.patch_service.validate", mocks["validate"]),
        patch("forge.services.verification_service.run", mocks["verify"]),
        patch("forge.services.verification_service.VerificationServiceError", Exception),
        patch("forge.services.policy_service.check", mocks["policy"]),
    ):
        run = engine.run(WorkflowTemplate.feature, "task")

    assert run.status == WorkflowStatus.failed
    stage_map = {s.name: s for s in run.stages}
    assert stage_map["plan"].status == WorkflowStageStatus.failed
    assert "patch" not in stage_map  # stages after failure are not added
    # Prior artifacts are preserved
    assert "repository" in run.artifacts
    assert "workset" in run.artifacts


# ---------------------------------------------------------------------------
# 7. Partial artifact registration on failure
# ---------------------------------------------------------------------------


def test_partial_artifacts_persisted(tmp_root: Path, registry: WorkflowRegistry):
    mocks = _mock_services()
    mocks["context"].side_effect = Exception("context error")
    engine = WorkflowEngine(tmp_root, registry=registry)
    with (
        patch("forge.services.repository_service.detect", mocks["repo"]),
        patch("forge.services.workset_service.create", mocks["workset_create"]),
        patch("forge.services.workset_service.generate_context", mocks["context"]),
        patch("forge.services.planning_service.generate", mocks["plan"]),
        patch("forge.services.implementation_service.ImplementationService", mocks["impl_cls"]),
        patch("forge.services.patch_service.validate", mocks["validate"]),
        patch("forge.services.verification_service.run", mocks["verify"]),
        patch("forge.services.verification_service.VerificationServiceError", Exception),
        patch("forge.services.policy_service.check", mocks["policy"]),
    ):
        run = engine.run(WorkflowTemplate.feature, "task")

    assert run.status == WorkflowStatus.failed
    assert "repository" in run.artifacts
    assert "workset" in run.artifacts
    # registry persisted the failed run
    persisted = registry.load(run.id)
    assert persisted is not None
    assert persisted["status"] == "failed"


# ---------------------------------------------------------------------------
# 8. No patch application occurs
# ---------------------------------------------------------------------------


def test_no_patch_applied(tmp_root: Path, registry: WorkflowRegistry):
    mocks = _mock_services()
    engine = WorkflowEngine(tmp_root, registry=registry)
    with (
        patch("forge.services.repository_service.detect", mocks["repo"]),
        patch("forge.services.workset_service.create", mocks["workset_create"]),
        patch("forge.services.workset_service.generate_context", mocks["context"]),
        patch("forge.services.planning_service.generate", mocks["plan"]),
        patch("forge.services.implementation_service.ImplementationService", mocks["impl_cls"]),
        patch("forge.services.patch_service.validate", mocks["validate"]),
        patch("forge.services.verification_service.run", mocks["verify"]),
        patch("forge.services.verification_service.VerificationServiceError", Exception),
        patch("forge.services.policy_service.check", mocks["policy"]),
        patch("forge.patches.service.resolve_patch_path", return_value=Path("/tmp/my.patch")),
        patch("forge.git.service.GitService.apply_check", mocks["git_apply_check"]),
        patch("forge.services.apply_service.apply") as apply_mock,
    ):
        run = engine.run(WorkflowTemplate.feature, "task")
        apply_mock.assert_not_called()

    assert run.status == WorkflowStatus.completed


# ---------------------------------------------------------------------------
# 9. Workflow artifact registered in registry
# ---------------------------------------------------------------------------


def test_workflow_artifact_registered(tmp_root: Path, registry: WorkflowRegistry):
    mocks = _mock_services()
    engine = WorkflowEngine(tmp_root, registry=registry)
    with (
        patch("forge.services.repository_service.detect", mocks["repo"]),
        patch("forge.services.workset_service.create", mocks["workset_create"]),
        patch("forge.services.workset_service.generate_context", mocks["context"]),
        patch("forge.services.planning_service.generate", mocks["plan"]),
        patch("forge.services.implementation_service.ImplementationService", mocks["impl_cls"]),
        patch("forge.services.patch_service.validate", mocks["validate"]),
        patch("forge.services.verification_service.run", mocks["verify"]),
        patch("forge.services.verification_service.VerificationServiceError", Exception),
        patch("forge.services.policy_service.check", mocks["policy"]),
        patch("forge.patches.service.resolve_patch_path", return_value=Path("/tmp/my.patch")),
        patch("forge.git.service.GitService.apply_check", mocks["git_apply_check"]),
    ):
        run = engine.run(WorkflowTemplate.feature, "task")

    run_file = registry._dir / f"{run.id}.json"
    assert run_file.exists()
    data = json.loads(run_file.read_text())
    assert data["id"] == run.id
    assert data["template"] == "feature"


# ---------------------------------------------------------------------------
# 10. WorkflowService API
# ---------------------------------------------------------------------------


def test_workflow_service_list_templates():
    templates = workflow_service.list_templates()
    names = {t["template"] for t in templates}
    assert {"feature", "bugfix", "refactor"}.issubset(names)


def test_workflow_service_run_unknown_template(tmp_root: Path):
    from forge.services.workflow_service import WorkflowServiceError

    with pytest.raises(WorkflowServiceError, match="Unknown workflow template"):
        workflow_service.run_workflow(tmp_root, "nonexistent", "task")


def test_workflow_service_list_runs(tmp_root: Path):
    reg = WorkflowRegistry.from_root(tmp_root)
    reg.save(WorkflowRun(id="x1", template=WorkflowTemplate.feature, task="t", repository="/r"))
    runs = workflow_service.list_runs(tmp_root)
    assert any(r["id"] == "x1" for r in runs)


def test_workflow_service_show_run(tmp_root: Path):
    reg = WorkflowRegistry.from_root(tmp_root)
    reg.save(WorkflowRun(id="y9", template=WorkflowTemplate.bugfix, task="fix", repository="/r"))
    result = workflow_service.show_run(tmp_root, "y9")
    assert result is not None
    assert result["id"] == "y9"
    assert workflow_service.show_run(tmp_root, "missing") is None


# ---------------------------------------------------------------------------
# 11. Existing services are reused, not reimplemented
# ---------------------------------------------------------------------------


def test_engine_delegates_to_existing_services(tmp_root: Path, registry: WorkflowRegistry):
    """Verify that the engine calls exactly the existing application services."""
    mocks = _mock_services()
    engine = WorkflowEngine(tmp_root, registry=registry)
    with (
        patch("forge.services.repository_service.detect", mocks["repo"]) as r_mock,
        patch("forge.services.workset_service.create", mocks["workset_create"]) as ws_mock,
        patch("forge.services.workset_service.generate_context", mocks["context"]) as ctx_mock,
        patch("forge.services.planning_service.generate", mocks["plan"]) as plan_mock,
        patch("forge.services.implementation_service.ImplementationService", mocks["impl_cls"]),
        patch("forge.services.patch_service.validate", mocks["validate"]),
        patch("forge.services.verification_service.run", mocks["verify"]) as ver_mock,
        patch("forge.services.verification_service.VerificationServiceError", Exception),
        patch("forge.services.policy_service.check", mocks["policy"]) as pol_mock,
        patch("forge.patches.service.resolve_patch_path", return_value=Path("/tmp/my.patch")),
        patch("forge.git.service.GitService.apply_check", mocks["git_apply_check"]),
    ):
        engine.run(WorkflowTemplate.feature, "task")

    r_mock.assert_called_once()
    ws_mock.assert_called_once()
    ctx_mock.assert_called_once()
    plan_mock.assert_called_once()
    ver_mock.assert_called_once()
    pol_mock.assert_called_once()


# ---------------------------------------------------------------------------
# 12. JSON output from WorkflowRun.to_dict
# ---------------------------------------------------------------------------


def test_workflow_run_json_output(tmp_root: Path, registry: WorkflowRegistry):
    mocks = _mock_services()
    engine = WorkflowEngine(tmp_root, registry=registry)
    with (
        patch("forge.services.repository_service.detect", mocks["repo"]),
        patch("forge.services.workset_service.create", mocks["workset_create"]),
        patch("forge.services.workset_service.generate_context", mocks["context"]),
        patch("forge.services.planning_service.generate", mocks["plan"]),
        patch("forge.services.implementation_service.ImplementationService", mocks["impl_cls"]),
        patch("forge.services.patch_service.validate", mocks["validate"]),
        patch("forge.services.verification_service.run", mocks["verify"]),
        patch("forge.services.verification_service.VerificationServiceError", Exception),
        patch("forge.services.policy_service.check", mocks["policy"]),
        patch("forge.patches.service.resolve_patch_path", return_value=Path("/tmp/my.patch")),
        patch("forge.git.service.GitService.apply_check", mocks["git_apply_check"]),
    ):
        run = engine.run(WorkflowTemplate.feature, "task")

    payload = run.to_dict()
    serialized = json.dumps(payload)  # must not raise
    loaded = json.loads(serialized)
    assert loaded["status"] == "completed"
    assert loaded["template"] == "feature"
    assert isinstance(loaded["stages"], list)
    assert "artifacts" in loaded


# ---------------------------------------------------------------------------
# 13. Artifact discovery includes workflow runs
# ---------------------------------------------------------------------------


def test_workflow_artifacts_discovered(tmp_root: Path):
    from forge.artifacts.discovery import discover_artifacts
    from forge.artifacts.models import ArtifactType

    reg = WorkflowRegistry.from_root(tmp_root)
    run = WorkflowRun(
        id="disc1",
        template=WorkflowTemplate.feature,
        task="disc task",
        repository=str(tmp_root),
        status=WorkflowStatus.completed,
    )
    reg.save(run)

    artifacts = discover_artifacts(tmp_root)
    workflow_artifacts = [a for a in artifacts if a.artifact_type == ArtifactType.workflow]
    assert any(a.name == "disc1" for a in workflow_artifacts)
