"""Verification domain service."""

from __future__ import annotations

from forge.verification.detector import detect_verification_strategy
from forge.verification.models import VerificationRequest, VerificationResult


def detect(request: VerificationRequest) -> VerificationResult:
    """Detect verification strategy without executing commands."""
    strategy = detect_verification_strategy(request.root)
    return VerificationResult(root=request.root, strategy=strategy, executed=False)
