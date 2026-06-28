"""Provider response parsing tests."""

from __future__ import annotations

from forge.models.anthropic import _extract_message_text
from forge.models.openai import _extract_response_text


def test_extract_openai_output_text() -> None:
    assert _extract_response_text({"output_text": "hello"}) == "hello"


def test_extract_openai_output_content_text() -> None:
    payload = {"output": [{"content": [{"text": "hello"}, {"text": "there"}]}]}

    assert _extract_response_text(payload) == "hello\nthere"


def test_extract_anthropic_message_text() -> None:
    payload = {"content": [{"type": "text", "text": "hello"}, {"type": "tool_use"}]}

    assert _extract_message_text(payload) == "hello"
