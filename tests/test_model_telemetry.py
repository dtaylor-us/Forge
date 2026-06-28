"""Model interaction telemetry tests."""

from __future__ import annotations

from forge.models.telemetry import estimate_tokens


def test_estimate_tokens_uses_local_size_estimate() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("hey") == 1
    assert estimate_tokens("12345678") == 2
