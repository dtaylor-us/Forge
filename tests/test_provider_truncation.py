"""Truncation-signal tests for the Anthropic and OpenAI providers.

These cover the same diagnosability gap fixed for Ollama (see
test_ollama_provider.py): a provider that stops generating because it hit an
output-length cap must be distinguishable from one that produced a complete
but malformed response, since they need very different repair strategies.
"""

from __future__ import annotations

from unittest.mock import patch

from forge.models.anthropic import AnthropicProvider
from forge.models.openai import OpenAIProvider


def test_anthropic_marks_truncated_on_max_tokens_stop_reason() -> None:
    provider = AnthropicProvider("fake-key", max_tokens=1024)
    payload = {
        "content": [{"type": "text", "text": "partial output"}],
        "stop_reason": "max_tokens",
    }
    with patch.object(AnthropicProvider, "_request", return_value=payload):
        response = provider.ask("Generate a patch", "claude-sonnet-5")

    assert response.truncated is True
    assert response.content == "partial output"


def test_anthropic_not_truncated_on_end_turn_stop_reason() -> None:
    provider = AnthropicProvider("fake-key", max_tokens=1024)
    payload = {
        "content": [{"type": "text", "text": "complete output"}],
        "stop_reason": "end_turn",
    }
    with patch.object(AnthropicProvider, "_request", return_value=payload):
        response = provider.ask("Generate a patch", "claude-sonnet-5")

    assert response.truncated is False


def test_openai_marks_truncated_on_max_output_tokens() -> None:
    provider = OpenAIProvider("fake-key", max_tokens=1024)
    payload = {
        "output_text": "partial output",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    with patch.object(OpenAIProvider, "_request", return_value=payload):
        response = provider.ask("Generate a patch", "gpt-5")

    assert response.truncated is True
    assert response.content == "partial output"


def test_openai_not_truncated_when_incomplete_details_absent() -> None:
    provider = OpenAIProvider("fake-key", max_tokens=1024)
    payload = {"output_text": "complete output"}
    with patch.object(OpenAIProvider, "_request", return_value=payload):
        response = provider.ask("Generate a patch", "gpt-5")

    assert response.truncated is False
