"""Policy evaluation against a patch and repository state."""

from __future__ import annotations

from typing import Any

from forge.policies.models import (
    CheckSeverity,
    CheckStatus,
    ForgePolicy,
    PolicyCheck,
    PolicyEvaluation,
    PolicyEvaluationStatus,
)


class PolicyEvaluator:
    """Evaluate a ForgePolicy against patch metadata, verification, and git state."""

    def evaluate(
        self,
        policy: ForgePolicy,
        patch_meta: dict[str, Any],
        git_status: dict[str, Any],
        verification_report: dict[str, Any] | None,
    ) -> PolicyEvaluation:
        checks: list[PolicyCheck] = []

        # --- patch checks ---
        checks.append(self._check_patch_valid(policy, patch_meta))
        checks.append(self._check_changed_files(policy, patch_meta))
        checks.append(self._check_added_lines(policy, patch_meta))
        checks.append(self._check_removed_lines(policy, patch_meta))

        # --- verification checks ---
        checks.append(self._check_verification(policy, verification_report))

        # --- git checks ---
        checks.append(self._check_git_repo(policy, git_status))
        checks.append(self._check_git_clean(policy, git_status))

        has_error = any(
            c.status == CheckStatus.fail and c.severity == CheckSeverity.error for c in checks
        )
        has_warn = any(c.status == CheckStatus.warn for c in checks)

        if has_error:
            status = PolicyEvaluationStatus.fail
        elif has_warn:
            status = PolicyEvaluationStatus.warn
        else:
            status = PolicyEvaluationStatus.pass_

        return PolicyEvaluation(status=status, checks=checks)

    # --- individual checks ---

    def _check_patch_valid(self, policy: ForgePolicy, patch_meta: dict[str, Any]) -> PolicyCheck:
        if not policy.patch.require_valid_patch:
            return PolicyCheck(
                "patch_valid", CheckStatus.skip, "Patch validity not required.", CheckSeverity.info
            )
        valid = patch_meta.get("valid", False)
        errors = patch_meta.get("validation_errors", [])
        if valid:
            return PolicyCheck(
                "patch_valid", CheckStatus.pass_, "Patch is valid.", CheckSeverity.info
            )
        msg = "Patch is invalid."
        if errors:
            msg += " " + "; ".join(errors)
        return PolicyCheck("patch_valid", CheckStatus.fail, msg, CheckSeverity.error)

    def _check_changed_files(self, policy: ForgePolicy, patch_meta: dict[str, Any]) -> PolicyCheck:
        count = len(patch_meta.get("affected_files", []))
        limit = policy.patch.max_changed_files
        if count <= limit:
            return PolicyCheck(
                "changed_files",
                CheckStatus.pass_,
                f"Changed files: {count} (limit: {limit}).",
                CheckSeverity.info,
            )
        return PolicyCheck(
            "changed_files",
            CheckStatus.fail,
            f"Changed files {count} exceeds limit {limit}.",
            CheckSeverity.error,
        )

    def _check_added_lines(self, policy: ForgePolicy, patch_meta: dict[str, Any]) -> PolicyCheck:
        added = patch_meta.get("added_lines", 0)
        limit = policy.patch.max_added_lines
        if added <= limit:
            return PolicyCheck(
                "added_lines",
                CheckStatus.pass_,
                f"Added lines: {added} (limit: {limit}).",
                CheckSeverity.info,
            )
        return PolicyCheck(
            "added_lines",
            CheckStatus.fail,
            f"Added lines {added} exceeds limit {limit}.",
            CheckSeverity.error,
        )

    def _check_removed_lines(self, policy: ForgePolicy, patch_meta: dict[str, Any]) -> PolicyCheck:
        removed = patch_meta.get("removed_lines", 0)
        limit = policy.patch.max_removed_lines
        if removed <= limit:
            return PolicyCheck(
                "removed_lines",
                CheckStatus.pass_,
                f"Removed lines: {removed} (limit: {limit}).",
                CheckSeverity.info,
            )
        return PolicyCheck(
            "removed_lines",
            CheckStatus.fail,
            f"Removed lines {removed} exceeds limit {limit}.",
            CheckSeverity.error,
        )

    def _check_verification(
        self, policy: ForgePolicy, verification_report: dict[str, Any] | None
    ) -> PolicyCheck:
        if not policy.verification.require_verification:
            return PolicyCheck(
                "verification",
                CheckStatus.skip,
                "Verification not required by policy.",
                CheckSeverity.info,
            )

        if verification_report is None:
            if policy.verification.allow_missing_verification:
                return PolicyCheck(
                    "verification",
                    CheckStatus.warn,
                    "No verification report found (allowed by policy).",
                    CheckSeverity.warning,
                )
            return PolicyCheck(
                "verification",
                CheckStatus.fail,
                "No verification report found. Run 'forge verify' first.",
                CheckSeverity.error,
            )

        overall = verification_report.get("overall_status", "")
        if not policy.verification.require_successful_verification:
            return PolicyCheck(
                "verification",
                CheckStatus.pass_,
                f"Verification found (status: {overall}). Success not required.",
                CheckSeverity.info,
            )

        if overall == "pass":
            return PolicyCheck(
                "verification",
                CheckStatus.pass_,
                "Verification passed.",
                CheckSeverity.info,
            )
        return PolicyCheck(
            "verification",
            CheckStatus.fail,
            f"Verification did not pass (status: {overall}). Run 'forge verify' to fix.",
            CheckSeverity.error,
        )

    def _check_git_repo(self, policy: ForgePolicy, git_status: dict[str, Any]) -> PolicyCheck:
        if not policy.git.require_git_repository:
            return PolicyCheck(
                "git_repository",
                CheckStatus.skip,
                "Git repository not required.",
                CheckSeverity.info,
            )
        is_repo = git_status.get("is_git_repository", False)
        if is_repo:
            return PolicyCheck(
                "git_repository", CheckStatus.pass_, "Git repository detected.", CheckSeverity.info
            )
        return PolicyCheck(
            "git_repository", CheckStatus.fail, "Not a git repository.", CheckSeverity.error
        )

    def _check_git_clean(self, policy: ForgePolicy, git_status: dict[str, Any]) -> PolicyCheck:
        if not policy.git.require_clean_worktree:
            return PolicyCheck(
                "git_clean",
                CheckStatus.skip,
                "Clean worktree not required.",
                CheckSeverity.info,
            )
        if not git_status.get("is_git_repository", False):
            return PolicyCheck(
                "git_clean",
                CheckStatus.skip,
                "Not a git repository — skipping clean check.",
                CheckSeverity.info,
            )
        clean = git_status.get("clean", False)
        if clean:
            return PolicyCheck(
                "git_clean",
                CheckStatus.pass_,
                "Working tree is clean.",
                CheckSeverity.info,
            )
        modified = git_status.get("modified_files", [])
        staged = git_status.get("staged_files", [])
        untracked = git_status.get("untracked_files", [])
        details = f"modified={len(modified)}, staged={len(staged)}, untracked={len(untracked)}"

        if not modified and not staged and untracked:
            message = (
                f"Working tree has untracked files only ({details}). "
                "Add them to .gitignore if they should be excluded, or run "
                "'git add' to track them, then re-run this check."
            )
        else:
            message = f"Working tree is dirty ({details}). Commit or stash changes first."

        return PolicyCheck(
            "git_clean",
            CheckStatus.fail,
            message,
            CheckSeverity.error,
        )
