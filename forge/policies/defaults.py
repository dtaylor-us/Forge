"""Default and config-file policy loading."""

from __future__ import annotations

from pathlib import Path

from forge.policies.models import (
    ApplyPolicy,
    ForgePolicy,
    GitPolicy,
    PatchPolicy,
    VerificationPolicy,
)

_POLICY_FILENAME = "policy.yaml"


def default_policy() -> ForgePolicy:
    return ForgePolicy(
        patch=PatchPolicy(),
        verification=VerificationPolicy(),
        git=GitPolicy(),
        apply=ApplyPolicy(),
    )


def load_policy(root: Path) -> ForgePolicy:
    """Load policy from .forge/policy.yaml if present, else return defaults."""
    policy_path = root / ".forge" / _POLICY_FILENAME
    if not policy_path.exists():
        return default_policy()

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return default_policy()

    try:
        raw = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return default_policy()

    patch_cfg = raw.get("patch", {})
    ver_cfg = raw.get("verification", {})
    git_cfg = raw.get("git", {})
    apply_cfg = raw.get("apply", {})

    return ForgePolicy(
        patch=PatchPolicy(
            require_valid_patch=patch_cfg.get("require_valid_patch", True),
            max_changed_files=patch_cfg.get("max_changed_files", 25),
            max_added_lines=patch_cfg.get("max_added_lines", 1000),
            max_removed_lines=patch_cfg.get("max_removed_lines", 1000),
        ),
        verification=VerificationPolicy(
            require_verification=ver_cfg.get("require_verification", True),
            allow_missing_verification=ver_cfg.get("allow_missing_verification", False),
            require_successful_verification=ver_cfg.get("require_successful_verification", True),
        ),
        git=GitPolicy(
            require_git_repository=git_cfg.get("require_git_repository", True),
            require_clean_worktree=git_cfg.get("require_clean_worktree", True),
        ),
        apply=ApplyPolicy(
            require_confirmation=apply_cfg.get("require_confirmation", True),
            allow_force=apply_cfg.get("allow_force", True),
        ),
    )
