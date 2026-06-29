"""Verification application service."""

from __future__ import annotations

from pathlib import Path

from forge.verification.executor import DEFAULT_TIMEOUT_SECONDS, VerificationExecutionError
from forge.verification.models import VerificationRequest
from forge.verification.report import VerificationStatus
from forge.verification.service import detect as detect_strategy
from forge.verification.service import execute as execute_verification


class VerificationServiceError(Exception):
    """Raised when verification infrastructure fails."""


def detect(root: Path) -> dict[str, object]:
    """Return a structured verification strategy without executing commands."""
    result = detect_strategy(VerificationRequest(root=root))
    return result.to_dict()


def run(
    root: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    output_path: Path | None = None,
    patch: str | None = None,
    plan: str | None = None,
    workset: str | None = None,
) -> dict[str, object]:
    """Execute repository verification and return a structured report."""
    try:
        report = execute_verification(
            root,
            timeout=timeout,
            output_path=output_path,
            patch=patch,
            plan=plan,
            workset=workset,
        )
    except (OSError, VerificationExecutionError) as exc:
        raise VerificationServiceError(str(exc)) from exc
    return report.to_dict()


def exit_code(report: dict[str, object]) -> int:
    """Return the deterministic CLI exit code for a verification report."""
    return 0 if report.get("overall_status") == VerificationStatus.pass_.value else 1
