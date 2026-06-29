"""Engineering policy data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PolicyEvaluationStatus(StrEnum):
    pass_ = "pass"
    warn = "warn"
    fail = "fail"


class CheckStatus(StrEnum):
    pass_ = "pass"
    warn = "warn"
    fail = "fail"
    skip = "skip"


class CheckSeverity(StrEnum):
    error = "error"
    warning = "warning"
    info = "info"


@dataclass(frozen=True)
class PolicyCheck:
    name: str
    status: CheckStatus
    message: str
    severity: CheckSeverity

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "severity": self.severity.value,
        }


@dataclass(frozen=True)
class PolicyEvaluation:
    status: PolicyEvaluationStatus
    checks: list[PolicyCheck]

    def blocking_failures(self) -> list[PolicyCheck]:
        return [
            c for c in self.checks
            if c.status == CheckStatus.fail and c.severity == CheckSeverity.error
        ]

    def warnings(self) -> list[PolicyCheck]:
        return [c for c in self.checks if c.status == CheckStatus.warn]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass(frozen=True)
class PatchPolicy:
    require_valid_patch: bool = True
    max_changed_files: int = 25
    max_added_lines: int = 1000
    max_removed_lines: int = 1000


@dataclass(frozen=True)
class VerificationPolicy:
    require_verification: bool = True
    allow_missing_verification: bool = False
    require_successful_verification: bool = True


@dataclass(frozen=True)
class GitPolicy:
    require_git_repository: bool = True
    require_clean_worktree: bool = True


@dataclass(frozen=True)
class ApplyPolicy:
    require_confirmation: bool = True
    allow_force: bool = True


@dataclass(frozen=True)
class ForgePolicy:
    patch: PatchPolicy = field(default_factory=PatchPolicy)
    verification: VerificationPolicy = field(default_factory=VerificationPolicy)
    git: GitPolicy = field(default_factory=GitPolicy)
    apply: ApplyPolicy = field(default_factory=ApplyPolicy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch": {
                "require_valid_patch": self.patch.require_valid_patch,
                "max_changed_files": self.patch.max_changed_files,
                "max_added_lines": self.patch.max_added_lines,
                "max_removed_lines": self.patch.max_removed_lines,
            },
            "verification": {
                "require_verification": self.verification.require_verification,
                "allow_missing_verification": self.verification.allow_missing_verification,
                "require_successful_verification": (
                    self.verification.require_successful_verification
                ),
            },
            "git": {
                "require_git_repository": self.git.require_git_repository,
                "require_clean_worktree": self.git.require_clean_worktree,
            },
            "apply": {
                "require_confirmation": self.apply.require_confirmation,
                "allow_force": self.apply.allow_force,
            },
        }
