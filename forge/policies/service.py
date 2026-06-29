"""Policy domain service — load, show, evaluate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.policies.defaults import load_policy
from forge.policies.evaluator import PolicyEvaluator
from forge.policies.models import ForgePolicy, PolicyEvaluation


def get_policy(root: Path) -> ForgePolicy:
    return load_policy(root)


def show_policy(root: Path) -> dict[str, Any]:
    return get_policy(root).to_dict()


def evaluate_policy(
    root: Path,
    patch_meta: dict[str, Any],
    git_status: dict[str, Any],
    verification_report: dict[str, Any] | None,
) -> PolicyEvaluation:
    policy = get_policy(root)
    return PolicyEvaluator().evaluate(policy, patch_meta, git_status, verification_report)
