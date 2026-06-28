"""Provider response parsing tests."""

from __future__ import annotations

import pytest

from forge.models.anthropic import _extract_message_text
from forge.models.errors import ModelProviderError
from forge.models.ollama import OllamaProvider
from forge.models.openai import _extract_response_text


def test_extract_openai_output_text() -> None:
    assert _extract_response_text({"output_text": "hello"}) == "hello"


def test_extract_openai_output_content_text() -> None:
    payload = {"output": [{"content": [{"text": "hello"}, {"text": "there"}]}]}

    assert _extract_response_text(payload) == "hello\nthere"


def test_extract_anthropic_message_text() -> None:
    payload = {"content": [{"type": "text", "text": "hello"}, {"type": "tool_use"}]}

    assert _extract_message_text(payload) == "hello"


def test_ollama_timeout_error_includes_context(monkeypatch) -> None:
    class TimeoutConnection:
        def __init__(self, host: str, port: int | None = None, timeout: int = 120) -> None:
            self.timeout = timeout

        def request(
            self,
            method: str,
            path: str,
            body: bytes | None = None,
            headers: dict[str, str] | None = None,
        ) -> None:
            raise TimeoutError("timed out")

        def close(self) -> None:
            return None

    monkeypatch.setattr("forge.models.ollama.HTTPConnection", TimeoutConnection)
    provider = OllamaProvider("http://localhost:11434", timeout_seconds=120)

    with pytest.raises(ModelProviderError) as exc_info:
        provider.ask("Hello", "qwen3:14b", timeout_seconds=180)

    message = str(exc_info.value)
    assert "qwen3:14b" in message
    assert "http://localhost:11434" in message
    assert "180 seconds" in message
    assert "smaller model" in message
