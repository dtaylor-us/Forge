"""Tests for Phase 6.1 Dogfood Readiness Hardening."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from forge.cli.app import app
from forge.git.service import GitServiceError
from forge.patches.service import save_patch_content
from forge.services import patch_service
from forge.verification.executor import VerificationExecutor
from forge.verification.report import VerificationStatus
from forge.verification.runner import CommandResult

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PATCH = """\
diff --git a/foo.py b/foo.py
index 1111111..2222222 100644
--- a/foo.py
+++ b/foo.py
@@ -1 +1 @@
-old
+new
"""

MALFORMED_PATCH = """\
diff --git a/foo.py b/foo.py
index 1111111..2222222 100644
--- a/foo.py
+++ b/foo.py
@@ -1,99 +1,99 @@
-old
+new
"""

IS_GIT = "forge.git.service.GitService.is_git_repository"
APPLY_CHECK = "forge.git.service.GitService.apply_check"
GIT_BRANCH = "forge.git.service.GitService.branch"


def _save(root: Path, content: str) -> str:
    patch = save_patch_content(root, content, prefix="test")
    return patch.name


# ---------------------------------------------------------------------------
# 1. Patch validation
# ---------------------------------------------------------------------------


def test_malformed_hunk_count_fails_via_apply_check(tmp_path: Path) -> None:
    """A patch that fails git apply --check should be reported as invalid."""
    name = _save(tmp_path, MALFORMED_PATCH)
    err = GitServiceError("corrupt patch at line 7")
    with (
        patch(IS_GIT, return_value=True),
        patch(APPLY_CHECK, side_effect=err),
    ):
        result = patch_service.validate(tmp_path, name)

    assert result["valid"] is False
    assert result["structural_valid"] is True
    assert result["apply_check_valid"] is False
    assert any("git apply --check failed" in e for e in result["validation_errors"])


def test_structural_valid_but_non_applicable_fails(tmp_path: Path) -> None:
    """A structurally valid patch that doesn't apply should fail validate."""
    name = _save(tmp_path, VALID_PATCH)
    with (
        patch(IS_GIT, return_value=True),
        patch(APPLY_CHECK, side_effect=GitServiceError("No such file")),
    ):
        result = patch_service.validate(tmp_path, name)

    assert result["valid"] is False
    assert result["structural_valid"] is True
    assert result["apply_check_valid"] is False


def test_valid_applicable_patch_passes(tmp_path: Path) -> None:
    """A structurally valid patch that passes apply_check should pass validation."""
    name = _save(tmp_path, VALID_PATCH)
    with (
        patch(IS_GIT, return_value=True),
        patch(APPLY_CHECK, return_value=None),
    ):
        result = patch_service.validate(tmp_path, name)

    assert result["valid"] is True
    assert result["structural_valid"] is True
    assert result["apply_check_valid"] is True
    assert result["validation_errors"] == []


def test_validate_json_includes_structural_and_apply_check(tmp_path: Path) -> None:
    """JSON output should include structural_valid and apply_check_valid fields."""
    name = _save(tmp_path, VALID_PATCH)
    with (
        patch(IS_GIT, return_value=True),
        patch(APPLY_CHECK, return_value=None),
    ):
        result = patch_service.validate(tmp_path, name)

    assert "structural_valid" in result
    assert "apply_check_valid" in result
    assert "suggestions" in result


def test_suggestions_included_on_failure(tmp_path: Path) -> None:
    """Suggestions should be non-empty when validation fails."""
    name = _save(tmp_path, VALID_PATCH)
    with (
        patch(IS_GIT, return_value=True),
        patch(APPLY_CHECK, side_effect=GitServiceError("err")),
    ):
        result = patch_service.validate(tmp_path, name)

    assert len(result["suggestions"]) > 0
    assert any("forge implement" in s or "forge patch" in s for s in result["suggestions"])


def test_validate_no_git_repo_skips_apply_check(tmp_path: Path) -> None:
    """When not in a git repo, apply_check_valid should be None (skipped)."""
    name = _save(tmp_path, VALID_PATCH)
    with patch(IS_GIT, return_value=False):
        result = patch_service.validate(tmp_path, name)

    assert result["structural_valid"] is True
    assert result["apply_check_valid"] is None
    assert result["valid"] is True


# ---------------------------------------------------------------------------
# 2. CLI: forge patch validate output
# ---------------------------------------------------------------------------


def test_cli_patch_validate_json_output(tmp_path: Path) -> None:
    """forge patch validate --json should include structural_valid, apply_check_valid."""
    name = _save(tmp_path, VALID_PATCH)
    with (
        patch(IS_GIT, return_value=True),
        patch(APPLY_CHECK, return_value=None),
    ):
        result = runner.invoke(
            app,
            ["patch", "validate", name, "--root", str(tmp_path), "--json"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["structural_valid"] is True
    assert data["apply_check_valid"] is True


def test_cli_patch_validate_fail_exit_code(tmp_path: Path) -> None:
    """forge patch validate should exit 1 when apply_check fails."""
    name = _save(tmp_path, VALID_PATCH)
    with (
        patch(IS_GIT, return_value=True),
        patch(APPLY_CHECK, side_effect=GitServiceError("err")),
    ):
        result = runner.invoke(
            app,
            ["patch", "validate", name, "--root", str(tmp_path)],
            catch_exceptions=False,
        )

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# 3. Apply — missing patch does not prompt
# ---------------------------------------------------------------------------


def test_apply_missing_patch_exits_before_prompt(tmp_path: Path) -> None:
    """forge apply with a non-existent patch should exit 1 without prompting."""
    result = runner.invoke(
        app,
        ["apply", "does-not-exist.patch", "--root", str(tmp_path)],
        input="y\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "error" in result.output.lower()
    assert "Apply patch" not in result.output


def test_apply_invalid_patch_exits_before_prompt(tmp_path: Path) -> None:
    """forge apply with an invalid patch should exit before prompting."""
    bad_content = "this is not a patch\n"
    name = _save(tmp_path, bad_content)
    patch_path = tmp_path / ".forge" / "patches" / name
    patch_path.write_text(bad_content, encoding="utf-8")

    result = runner.invoke(
        app,
        ["apply", name, "--root", str(tmp_path)],
        input="y\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    assert "Apply patch" not in result.output


# ---------------------------------------------------------------------------
# 4. Apply --yes does not bypass policy
# ---------------------------------------------------------------------------


def test_apply_yes_still_enforces_policy(tmp_path: Path) -> None:
    """--yes skips confirmation but policy must still be evaluated."""
    from forge.services.apply_service import PolicyBlockedError

    name = _save(tmp_path, VALID_PATCH)
    err = PolicyBlockedError("policy blocked", {"checks": [], "status": "fail"})
    with (
        patch(IS_GIT, return_value=True),
        patch(APPLY_CHECK, return_value=None),
        patch("forge.services.apply_service.apply", side_effect=err),
    ):
        result = runner.invoke(
            app,
            ["apply", "--yes", name, "--root", str(tmp_path)],
            catch_exceptions=False,
        )

    assert result.exit_code == 1
    assert "policy" in result.output.lower() or "blocked" in result.output.lower()


def test_apply_force_can_bypass_allowed_policy_failure(tmp_path: Path) -> None:
    """--force can override policy when policy.apply.allow_force is true."""
    name = _save(tmp_path, VALID_PATCH)
    record = {
        "id": "test-id",
        "patch": name,
        "affected_files": [],
        "policy_status": "fail",
        "applied_at": "2026-01-01T00:00:00+00:00",
        "branch": "main",
        "commit_before": "abc123",
        "forced": True,
        "confirmed": True,
        "status": "applied",
        "verification_report": None,
    }
    with (
        patch(IS_GIT, return_value=True),
        patch(APPLY_CHECK, return_value=None),
        patch("forge.services.apply_service.apply", return_value=record),
    ):
        result = runner.invoke(
            app,
            ["apply", "--yes", "--force", name, "--root", str(tmp_path)],
            catch_exceptions=False,
        )

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 5. Workflow validate uses GitService.apply_check
# ---------------------------------------------------------------------------


def test_workflow_validate_uses_git_service(tmp_path: Path) -> None:
    """Workflow validate stage must call GitService.apply_check, not subprocess.run."""
    from forge.workflows.engine import WorkflowEngine
    from forge.workflows.models import WorkflowTemplate
    from forge.workflows.registry import WorkflowRegistry

    registry = WorkflowRegistry(tmp_path / ".forge" / "workflows")
    engine = WorkflowEngine(tmp_path, registry=registry)

    apply_check_calls: list[Any] = []

    def _apply_check(patch_path: Path) -> None:
        apply_check_calls.append(patch_path)

    impl_result = MagicMock()
    impl_result.valid = True
    impl_result.patch_path = Path("/tmp/my.patch")
    impl_result.patch_name = "my.patch"
    impl_result.validation_errors = []
    impl_result.to_dict.return_value = {
        "patch_name": "my.patch",
        "patch_path": "/tmp/my.patch",
        "affected_files": [],
        "validation_errors": [],
        "valid": True,
    }
    impl_cls = MagicMock()
    impl_cls.return_value.implement.return_value = impl_result

    validate_result = {
        "valid": True,
        "structural_valid": True,
        "apply_check_valid": True,
        "name": "my.patch",
        "validation_errors": [],
    }

    with (
        patch(
            "forge.services.repository_service.detect",
            return_value={"root_path": str(tmp_path), "languages": ["python"]},
        ),
        patch(
            "forge.services.workset_service.create",
            return_value={"name": "ws", "files": []},
        ),
        patch(
            "forge.services.workset_service.generate_context",
            return_value={"file_count": 1, "path": "/tmp/ctx.md"},
        ),
        patch(
            "forge.services.planning_service.generate",
            return_value={"task": "t", "saved_path": "/tmp/p.md", "model": "x"},
        ),
        patch("forge.services.implementation_service.ImplementationService", impl_cls),
        patch("forge.services.patch_service.validate", return_value=validate_result),
        patch(
            "forge.patches.service.resolve_patch_path",
            return_value=Path("/tmp/my.patch"),
        ),
        patch(APPLY_CHECK, side_effect=_apply_check),
        patch(
            "forge.services.verification_service.run",
            return_value={"overall_status": "pass", "summary": {}},
        ),
        patch("forge.services.verification_service.VerificationServiceError", Exception),
        patch(
            "forge.services.policy_service.check",
            return_value={
                "patch": "my.patch",
                "evaluation": {"status": "pass", "checks": []},
            },
        ),
    ):
        engine.run(WorkflowTemplate.feature, "add a feature")

    assert len(apply_check_calls) >= 1, "GitService.apply_check must be called by validate stage"


def test_workflow_validate_failure_includes_next_actions(tmp_path: Path) -> None:
    """Workflow validate failure error should include next-step guidance."""
    from forge.workflows.engine import WorkflowEngine
    from forge.workflows.models import WorkflowTemplate
    from forge.workflows.registry import WorkflowRegistry

    registry = WorkflowRegistry(tmp_path / ".forge" / "workflows")
    engine = WorkflowEngine(tmp_path, registry=registry)

    impl_result = MagicMock()
    impl_result.valid = True
    impl_result.patch_path = Path("/tmp/my.patch")
    impl_result.patch_name = "my.patch"
    impl_result.validation_errors = []
    impl_result.to_dict.return_value = {
        "patch_name": "my.patch",
        "patch_path": "/tmp/my.patch",
        "affected_files": [],
        "validation_errors": [],
        "valid": True,
    }
    impl_cls = MagicMock()
    impl_cls.return_value.implement.return_value = impl_result

    validate_result = {
        "valid": True,
        "structural_valid": True,
        "apply_check_valid": None,
        "name": "my.patch",
        "validation_errors": [],
    }

    with (
        patch(
            "forge.services.repository_service.detect",
            return_value={"root_path": str(tmp_path), "languages": []},
        ),
        patch(
            "forge.services.workset_service.create",
            return_value={"name": "ws", "files": []},
        ),
        patch(
            "forge.services.workset_service.generate_context",
            return_value={"file_count": 0, "path": None},
        ),
        patch(
            "forge.services.planning_service.generate",
            return_value={"task": "t", "saved_path": None, "model": "x"},
        ),
        patch("forge.services.implementation_service.ImplementationService", impl_cls),
        patch("forge.services.patch_service.validate", return_value=validate_result),
        patch(
            "forge.patches.service.resolve_patch_path",
            return_value=Path("/tmp/my.patch"),
        ),
        patch(
            APPLY_CHECK,
            side_effect=GitServiceError("corrupt patch at line 11"),
        ),
    ):
        run = engine.run(WorkflowTemplate.feature, "add something")

    failed_stages = [s for s in run.stages if s.status.value == "failed"]
    assert failed_stages, "validate stage should fail"
    error_text = failed_stages[0].error or ""
    assert (
        "forge patch show" in error_text
        or "Next steps" in error_text
        or "inspect" in error_text
    )


# ---------------------------------------------------------------------------
# 6. Verification recommendations
# ---------------------------------------------------------------------------


def _make_step_result(
    tool: str,
    kind: str,
    command: str,
    status: VerificationStatus,
    exception: str | None = None,
) -> Any:
    from forge.verification.report import VerificationStepResult

    exit_code: int | None
    if status == VerificationStatus.error:
        exit_code = None
    elif status == VerificationStatus.pass_:
        exit_code = 0
    else:
        exit_code = 1
    return VerificationStepResult(
        tool=tool,
        command=command,
        working_directory=Path("/tmp"),
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:01+00:00",
        duration=1.0,
        exit_code=exit_code,
        stdout="",
        stderr="",
        status=status,
        exception=exception,
        kind=kind,
        name=f"{tool} {kind}",
    )


def test_black_failure_produces_recommendation(tmp_path: Path) -> None:
    from forge.verification.executor import _build_recommendations

    step = _make_step_result("black", "formatter", "black --check .", VerificationStatus.fail)
    recs = _build_recommendations([step])
    assert any("black" in r.lower() for r in recs)


def test_ruff_failure_produces_recommendation(tmp_path: Path) -> None:
    from forge.verification.executor import _build_recommendations

    step = _make_step_result("ruff", "linter", "ruff check .", VerificationStatus.fail)
    recs = _build_recommendations([step])
    assert any("ruff" in r.lower() for r in recs)


def test_pytest_failure_produces_recommendation(tmp_path: Path) -> None:
    from forge.verification.executor import _build_recommendations

    step = _make_step_result("pytest", "tests", "pytest", VerificationStatus.fail)
    recs = _build_recommendations([step])
    assert any("pytest" in r.lower() for r in recs)


def test_npm_test_failure_produces_recommendation(tmp_path: Path) -> None:
    from forge.verification.executor import _build_recommendations

    step = _make_step_result("npm", "tests", "npm test", VerificationStatus.fail)
    recs = _build_recommendations([step])
    assert any("npm" in r.lower() for r in recs)


def test_build_failure_produces_recommendation(tmp_path: Path) -> None:
    from forge.verification.executor import _build_recommendations

    step = _make_step_result("make", "build", "make build", VerificationStatus.fail)
    recs = _build_recommendations([step])
    assert any("build" in r.lower() for r in recs)


def test_passed_steps_produce_no_recommendations(tmp_path: Path) -> None:
    from forge.verification.executor import _build_recommendations

    steps = [
        _make_step_result("black", "formatter", "black --check .", VerificationStatus.pass_),
        _make_step_result("pytest", "tests", "pytest", VerificationStatus.pass_),
    ]
    recs = _build_recommendations(steps)
    assert recs == []


def test_executor_populates_recommendations_on_failure(tmp_path: Path) -> None:
    """VerificationExecutor.execute() should populate recommendations when steps fail."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.black]\nline-length = 88\n[tool.pytest.ini_options]\ntestpaths = []\n",
        encoding="utf-8",
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    fail_result = CommandResult(
        command="black --check .",
        working_directory=tmp_path,
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:01+00:00",
        duration=1.0,
        exit_code=1,
        stdout="",
        stderr="would reformat foo.py",
    )

    class _FailRunner:
        def run(
            self,
            command: str,
            working_directory: Path,
            *,
            timeout: float,
        ) -> CommandResult:
            return fail_result

    executor = VerificationExecutor(runner=_FailRunner())
    report = executor.execute(tmp_path)
    assert len(report.recommendations) > 0


# ---------------------------------------------------------------------------
# 7. Telemetry does not appear on stdout
# ---------------------------------------------------------------------------


def test_model_telemetry_level_is_warning_in_non_verbose() -> None:
    """Non-verbose mode should set logging to WARNING to suppress INFO telemetry."""
    import logging

    from forge.utils.logging import configure_logging

    configure_logging(verbose=False)
    assert logging.getLogger().level == logging.WARNING


def test_verbose_mode_enables_debug_logging() -> None:
    """--verbose should enable DEBUG level."""
    import logging

    from forge.utils.logging import configure_logging

    configure_logging(verbose=True)
    assert logging.getLogger().level == logging.DEBUG


# ---------------------------------------------------------------------------
# 8. Implementation prompt — existing files are labelled
# ---------------------------------------------------------------------------


def test_implementation_prompt_labels_existing_files() -> None:
    """The implementation prompt should clearly label workset files as existing."""
    from datetime import UTC, datetime

    from forge.context.bundle import ContextBundle, ContextBundleFile
    from forge.execution.execution_prompt import build_implementation_prompt
    from forge.planning.planner import ImplementationPlan

    bundle = ContextBundle(
        workset_name="my-workset",
        query="add feature",
        root="/repo",
        generated_at="2026-01-01T00:00:00+00:00",
        files=[
            ContextBundleFile(
                path="forge/service.py",
                category="source",
                score=10,
                line_count=50,
                char_count=1000,
                token_estimate=250,
            )
        ],
    )
    plan = ImplementationPlan(
        task="add feature",
        workset_name="my-workset",
        model="test-model",
        generated_at=datetime.now(tz=UTC),
        content="Do the thing.",
    )
    prompt = build_implementation_prompt("add feature", bundle, plan, "test-model")
    assert "ALREADY EXIST" in prompt or "existing" in prompt.lower()


def test_implementation_prompt_forbids_dev_null_for_existing_files() -> None:
    """The prompt system instructions must warn against /dev/null for existing files."""
    from forge.execution.execution_prompt import _IMPLEMENTATION_SYSTEM_INSTRUCTIONS

    text = _IMPLEMENTATION_SYSTEM_INSTRUCTIONS.lower()
    assert "/dev/null" in text
    assert "existing" in text or "exist" in text


# ---------------------------------------------------------------------------
# 9. Not-found exit codes consistency
# ---------------------------------------------------------------------------


def test_patch_validate_not_found_exits_1(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["patch", "validate", "missing.patch", "--root", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 1


def test_apply_not_found_exits_1(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["apply", "missing.patch", "--root", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# 10. Dashboard branch detection
# ---------------------------------------------------------------------------


def test_repository_service_detect_includes_branch(tmp_path: Path) -> None:
    """detect() should include current_branch in its output."""
    from forge.services.repository_service import detect

    with (
        patch(IS_GIT, return_value=True),
        patch(GIT_BRANCH, return_value="main"),
    ):
        result = detect(tmp_path)

    assert "current_branch" in result
    assert result["current_branch"] == "main"


def test_repository_service_detect_branch_none_when_no_git(tmp_path: Path) -> None:
    """detect() should return None for current_branch when not in a git repo."""
    from forge.services.repository_service import detect

    with patch(IS_GIT, return_value=False):
        result = detect(tmp_path)

    assert result["current_branch"] is None
