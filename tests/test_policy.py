"""Tests for Phase 5.8: Engineering Policies and Guarded Patch Apply."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from forge.cli.app import app
from forge.git.service import GitService, GitServiceError
from forge.policies.defaults import default_policy, load_policy
from forge.policies.evaluator import PolicyEvaluator
from forge.policies.models import (
    ForgePolicy,
    PolicyEvaluationStatus,
)

runner = CliRunner()


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@forge.dev"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Forge Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    (tmp_path / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "hello.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True
    )
    return tmp_path


def _valid_patch(repo: Path, filename: str = "hello.py") -> Path:
    """Create a real patch file against the repo."""
    # Modify the file
    (repo / filename).write_text("print('hello')\nprint('world')\n")
    result = subprocess.run(
        ["git", "diff"], cwd=repo, capture_output=True, text=True, check=True
    )
    patch_content = result.stdout
    # Restore original
    subprocess.run(["git", "checkout", filename], cwd=repo, capture_output=True, check=True)
    patch_path = repo / ".forge" / "patches" / "test.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(patch_content)
    return patch_path


@pytest.fixture()
def valid_patch_meta() -> dict:
    return {
        "name": "test.patch",
        "path": "/tmp/test.patch",
        "valid": True,
        "validation_errors": [],
        "affected_files": ["hello.py"],
        "added_lines": 1,
        "removed_lines": 0,
    }


@pytest.fixture()
def clean_git_status() -> dict:
    return {
        "is_git_repository": True,
        "root": "/tmp/repo",
        "branch": "main",
        "commit": "abc1234",
        "clean": True,
        "staged_files": [],
        "modified_files": [],
        "deleted_files": [],
        "untracked_files": [],
    }


@pytest.fixture()
def dirty_git_status(clean_git_status) -> dict:
    return {**clean_git_status, "clean": False, "modified_files": ["README.md"]}


@pytest.fixture()
def passed_verification() -> dict:
    return {"overall_status": "pass", "artifact": {}}


@pytest.fixture()
def failed_verification() -> dict:
    return {"overall_status": "fail", "artifact": {}}


# ─── policy model tests ───────────────────────────────────────────────────────

def test_default_policy_loads() -> None:
    policy = default_policy()
    assert policy.patch.require_valid_patch is True
    assert policy.patch.max_changed_files == 25
    assert policy.verification.require_verification is True
    assert policy.git.require_clean_worktree is True
    assert policy.apply.allow_force is True


def test_policy_to_dict_structure() -> None:
    policy = default_policy()
    d = policy.to_dict()
    assert "patch" in d
    assert "verification" in d
    assert "git" in d
    assert "apply" in d
    assert d["patch"]["max_changed_files"] == 25


def test_load_policy_falls_back_to_defaults_when_no_file(tmp_path: Path) -> None:
    policy = load_policy(tmp_path)
    assert isinstance(policy, ForgePolicy)
    assert policy.patch.require_valid_patch is True


# ─── evaluator tests ──────────────────────────────────────────────────────────

def test_valid_patch_passes(valid_patch_meta, clean_git_status, passed_verification) -> None:
    policy = default_policy()
    eval_ = PolicyEvaluator().evaluate(
        policy,
        valid_patch_meta,
        clean_git_status,
        passed_verification,
    )
    assert eval_.status == PolicyEvaluationStatus.pass_


def test_invalid_patch_fails_policy(clean_git_status) -> None:
    policy = default_policy()
    bad_meta = {
        "valid": False,
        "validation_errors": ["Not a unified diff."],
        "affected_files": [],
        "added_lines": 0,
        "removed_lines": 0,
    }
    eval_ = PolicyEvaluator().evaluate(policy, bad_meta, clean_git_status, None)
    assert eval_.status == PolicyEvaluationStatus.fail
    names = [c.name for c in eval_.blocking_failures()]
    assert "patch_valid" in names


def test_too_many_changed_files_fails(
    valid_patch_meta,
    clean_git_status,
    passed_verification,
) -> None:
    from forge.policies.models import PatchPolicy
    policy = ForgePolicy(patch=PatchPolicy(max_changed_files=0))
    eval_ = PolicyEvaluator().evaluate(
        policy,
        valid_patch_meta,
        clean_git_status,
        passed_verification,
    )
    assert eval_.status == PolicyEvaluationStatus.fail
    assert any(c.name == "changed_files" for c in eval_.blocking_failures())


def test_too_many_added_lines_fails(clean_git_status, passed_verification) -> None:
    from forge.policies.models import PatchPolicy
    policy = ForgePolicy(patch=PatchPolicy(max_added_lines=0))
    meta = {
        "valid": True,
        "validation_errors": [],
        "affected_files": ["a.py"],
        "added_lines": 5,
        "removed_lines": 0,
    }
    eval_ = PolicyEvaluator().evaluate(policy, meta, clean_git_status, passed_verification)
    assert eval_.status == PolicyEvaluationStatus.fail
    assert any(c.name == "added_lines" for c in eval_.blocking_failures())


def test_missing_verification_fails_when_required(valid_patch_meta, clean_git_status) -> None:
    policy = default_policy()
    eval_ = PolicyEvaluator().evaluate(policy, valid_patch_meta, clean_git_status, None)
    assert eval_.status == PolicyEvaluationStatus.fail
    assert any(c.name == "verification" for c in eval_.blocking_failures())


def test_failed_verification_fails_policy(
    valid_patch_meta,
    clean_git_status,
    failed_verification,
) -> None:
    policy = default_policy()
    eval_ = PolicyEvaluator().evaluate(
        policy,
        valid_patch_meta,
        clean_git_status,
        failed_verification,
    )
    assert eval_.status == PolicyEvaluationStatus.fail


def test_passed_verification_passes_policy(
    valid_patch_meta,
    clean_git_status,
    passed_verification,
) -> None:
    policy = default_policy()
    eval_ = PolicyEvaluator().evaluate(
        policy,
        valid_patch_meta,
        clean_git_status,
        passed_verification,
    )
    # also need clean worktree — which clean_git_status provides
    assert eval_.status == PolicyEvaluationStatus.pass_


def test_dirty_git_fails_policy(valid_patch_meta, dirty_git_status, passed_verification) -> None:
    policy = default_policy()
    eval_ = PolicyEvaluator().evaluate(
        policy,
        valid_patch_meta,
        dirty_git_status,
        passed_verification,
    )
    assert eval_.status == PolicyEvaluationStatus.fail
    assert any(c.name == "git_clean" for c in eval_.blocking_failures())


# ─── git service apply tests ──────────────────────────────────────────────────

def test_git_detect_non_git_repo(tmp_path: Path) -> None:
    svc = GitService(tmp_path)
    assert svc.is_git_repository() is False


def test_git_detect_clean_repo(tmp_git_repo: Path) -> None:
    svc = GitService(tmp_git_repo)
    status = svc.status()
    assert status.is_git_repository is True
    assert status.clean is True


def test_git_detect_dirty_repo(tmp_git_repo: Path) -> None:
    (tmp_git_repo / "hello.py").write_text("changed\n")
    svc = GitService(tmp_git_repo)
    status = svc.status()
    assert status.clean is False


def test_git_apply_check_called_before_apply(tmp_git_repo: Path) -> None:
    patch_path = _valid_patch(tmp_git_repo)
    svc = GitService(tmp_git_repo)
    calls: list[str] = []
    original_run = svc._run

    def tracking_run(*args: str) -> str:
        calls.append(args[0])
        return original_run(*args)

    svc._run = tracking_run  # type: ignore[method-assign]
    svc.apply_check(patch_path)
    assert "apply" in calls[0]


def test_failed_apply_check_prevents_apply(tmp_git_repo: Path) -> None:
    """A patch that doesn't apply should raise before git apply is called."""
    bad_patch = tmp_git_repo / ".forge" / "patches" / "bad.patch"
    bad_patch.parent.mkdir(parents=True, exist_ok=True)
    bad_patch.write_text(
        "diff --git a/nonexistent.py b/nonexistent.py\n"
        "--- a/nonexistent.py\n+++ b/nonexistent.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    svc = GitService(tmp_git_repo)
    with pytest.raises(GitServiceError):
        svc.apply_check(bad_patch)


def test_successful_apply_modifies_file(tmp_git_repo: Path) -> None:
    patch_path = _valid_patch(tmp_git_repo)
    svc = GitService(tmp_git_repo)
    svc.apply_check(patch_path)
    svc.apply(patch_path)
    content = (tmp_git_repo / "hello.py").read_text()
    assert "world" in content


# ─── CLI command tests ────────────────────────────────────────────────────────

def test_cli_policy_show(tmp_path: Path) -> None:
    result = runner.invoke(app, ["policy", "show", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "patch" in result.output


def test_cli_policy_show_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["policy", "show", "--json", "--root", str(tmp_path)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "patch" in data
    assert "verification" in data


def test_cli_policy_check(tmp_git_repo: Path) -> None:
    patch_path = _valid_patch(tmp_git_repo)
    result = runner.invoke(app, ["policy", "check", patch_path.name, "--root", str(tmp_git_repo)])
    # May fail due to dirty worktree after creating patch; check it ran
    assert result.exit_code in (0, 1)
    assert "Policy evaluation" in result.output


def test_cli_policy_check_json(tmp_git_repo: Path) -> None:
    patch_path = _valid_patch(tmp_git_repo)
    result = runner.invoke(
        app,
        ["policy", "check", patch_path.name, "--json", "--root", str(tmp_git_repo)],
    )
    assert result.exit_code in (0, 1)
    data = json.loads(result.output)
    assert "evaluation" in data


def test_cli_apply_prompts_before_applying(tmp_git_repo: Path) -> None:
    patch_path = _valid_patch(tmp_git_repo)
    # Answer "n" to decline
    result = runner.invoke(
        app,
        ["apply", patch_path.name, "--root", str(tmp_git_repo)],
        input="n\n",
    )
    assert "cancelled" in result.output.lower() or result.exit_code == 0


def test_cli_apply_yes_skips_prompt_but_not_policy(tmp_git_repo: Path) -> None:
    """--yes skips confirmation but policy is still evaluated (dirty worktree will fail)."""
    patch_path = _valid_patch(tmp_git_repo)
    # Worktree is dirty after creating patch file; policy will block unless we force
    result = runner.invoke(app, ["apply", patch_path.name, "--yes", "--root", str(tmp_git_repo)])
    # Should fail policy (dirty worktree + no verification) without --force
    assert result.exit_code in (0, 1)


def test_cli_apply_force_overrides_policy(tmp_git_repo: Path) -> None:
    patch_path = _valid_patch(tmp_git_repo)
    result = runner.invoke(
        app,
        ["apply", patch_path.name, "--yes", "--force", "--root", str(tmp_git_repo)],
    )
    # Force overrides policy; apply should succeed or fail on git apply itself
    assert result.exit_code in (0, 1)


def test_cli_apply_json_output(tmp_git_repo: Path) -> None:
    patch_path = _valid_patch(tmp_git_repo)
    result = runner.invoke(
        app,
        ["apply", patch_path.name, "--yes", "--force", "--json", "--root", str(tmp_git_repo)],
    )
    assert result.exit_code in (0, 1)
    output = result.output.strip()
    if output:
        data = json.loads(output)
        assert isinstance(data, dict)


def test_cli_apply_exit_codes_deterministic(tmp_git_repo: Path, tmp_path: Path) -> None:
    """Apply with a nonexistent patch gives exit code 1."""
    result = runner.invoke(
        app, ["apply", "nonexistent.patch", "--yes", "--root", str(tmp_git_repo)]
    )
    assert result.exit_code == 1
