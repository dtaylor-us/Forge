"""Verification application service."""

from __future__ import annotations

from pathlib import Path

from forge.verification.models import VerificationRequest
from forge.verification.service import detect as detect_strategy


def detect(root: Path) -> dict[str, object]:
    """Return a structured verification strategy without executing commands."""
    result = detect_strategy(VerificationRequest(root=root))
    return result.to_dict()
