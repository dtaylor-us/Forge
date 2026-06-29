"""Guarded patch apply service."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge.git.service import GitService, GitServiceError
from forge.patches import PatchError, validate_patch_file
from forge.patches.service import resolve_patch_path
from forge.policies.models import PolicyEvaluationStatus
from forge.policies.service import evaluate_policy
from forge.project.paths import ForgePaths
from forge.services.policy_service import _load_verification_report, _resolve_report_path


class ApplyError(Exception):
    """Raised when patch apply is refused or fails."""


class PolicyBlockedError(ApplyError):
    """Raised when policy evaluation fails and force is not allowed."""

    def __init__(self, message: str, evaluation: dict[str, Any]) -> None:
        super().__init__(message)
        self.evaluation = evaluation


def apply(
    root: Path,
    patch_name_or_path: str,
    *,
    verification_path: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Apply a patch after validation, policy evaluation, and git apply --check.

    Raises ApplyError / PolicyBlockedError on failure.
    Does not commit. Does not call models. Does not repair.
    """
    paths = ForgePaths.from_root(root)
    git_svc = GitService(cwd=root)

    # 1. Resolve and validate patch
    try:
        patch_path = resolve_patch_path(root, patch_name_or_path)
    except PatchError as exc:
        raise ApplyError(str(exc)) from exc

    patch_meta = validate_patch_file(root, patch_name_or_path).to_dict()
    if not patch_meta["valid"]:
        errors = "; ".join(patch_meta.get("validation_errors", []))
        raise ApplyError(f"Patch is invalid: {errors}")

    # 2. git apply --check
    try:
        git_svc.apply_check(patch_path)
    except GitServiceError as exc:
        raise ApplyError(f"git apply --check failed: {exc}") from exc

    # 3. Load verification report
    verification_report = _load_verification_report(root, _resolve_str(root, verification_path))

    # 4. Evaluate policy
    git_status = git_svc.status().to_dict()
    evaluation = evaluate_policy(root, patch_meta, git_status, verification_report)

    if evaluation.status == PolicyEvaluationStatus.fail:
        from forge.policies.defaults import load_policy

        policy = load_policy(root)
        if not force or not policy.apply.allow_force:
            raise PolicyBlockedError(
                "Policy evaluation failed. Use --force to override if allowed.",
                evaluation.to_dict(),
            )

    # 5. Apply patch
    commit_before = git_status.get("commit")
    branch = git_status.get("branch")
    try:
        git_svc.apply(patch_path)
    except GitServiceError as exc:
        raise ApplyError(f"git apply failed: {exc}") from exc

    # 6. Persist apply record
    record = _build_record(
        patch_meta=patch_meta,
        verification_report=verification_report,
        evaluation=evaluation.to_dict(),
        branch=branch,
        commit_before=commit_before,
        forced=force,
        status="applied",
    )
    _persist_record(paths, record)

    return record


def _resolve_str(root: Path, path_or_name: str | None) -> str | None:
    if path_or_name is None:
        return None
    p = _resolve_report_path(root, path_or_name)
    return str(p) if p else path_or_name


def _build_record(
    *,
    patch_meta: dict[str, Any],
    verification_report: dict[str, Any] | None,
    evaluation: dict[str, Any],
    branch: str | None,
    commit_before: str | None,
    forced: bool,
    status: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "patch": patch_meta["name"],
        "affected_files": patch_meta.get("affected_files", []),
        "verification_report": verification_report.get("artifact", {}).get("relative_path") if verification_report else None,
        "policy_status": evaluation.get("status"),
        "applied_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "branch": branch,
        "commit_before": commit_before,
        "forced": forced,
        "confirmed": True,
        "status": status,
    }


def _persist_record(paths: ForgePaths, record: dict[str, Any]) -> None:
    paths.applications_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{ts}-{record['id'][:8]}.json"
    (paths.applications_dir / filename).write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
