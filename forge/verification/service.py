"""Verification domain service."""

from __future__ import annotations

from pathlib import Path

from forge.verification.artifact import register_report
from forge.verification.detector import detect_verification_strategy
from forge.verification.executor import DEFAULT_TIMEOUT_SECONDS, VerificationExecutor
from forge.verification.models import VerificationRequest, VerificationResult
from forge.verification.report import VerificationReport


def detect(request: VerificationRequest) -> VerificationResult:
    """Detect verification strategy without executing commands."""
    strategy = detect_verification_strategy(request.root)
    return VerificationResult(root=request.root, strategy=strategy, executed=False)


def execute(
    root: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    output_path: Path | None = None,
    patch: str | None = None,
    plan: str | None = None,
    workset: str | None = None,
    executor: VerificationExecutor | None = None,
) -> VerificationReport:
    """Execute verification and persist a report artifact."""
    active_executor = executor or VerificationExecutor()
    report = active_executor.execute(
        root,
        timeout=timeout,
        metadata={"patch": patch, "plan": plan, "workset": workset},
    )
    return register_report(root, report, output_path=output_path)
