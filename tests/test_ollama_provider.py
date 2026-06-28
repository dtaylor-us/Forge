"""Ollama provider tests."""

from __future__ import annotations

import json
from typing import Any

import pytest

from forge.models.errors import ModelProviderError
from forge.models.ollama import OllamaProvider


class FakeHTTPResponse:
    def __init__(self, status: int, payload: dict[str, Any] | str) -> None:
        self.status = status
        self.payload = payload

    def read(self) -> bytes:
        if isinstance(self.payload, str):
            return self.payload.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")


class FakeHTTPConnection:
    response = FakeHTTPResponse(200, {})
    requests: list[dict[str, Any]] = []
    fail_with: Exception | None = None

    def __init__(self, host: str, port: int | None = None, timeout: int = 120) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if self.fail_with:
            raise self.fail_with
        self.requests.append(
            {
                "host": self.host,
                "port": self.port,
                "timeout": self.timeout,
                "method": method,
                "path": path,
                "body": json.loads(body.decode("utf-8")) if body else None,
                "headers": headers or {},
            }
        )

    def getresponse(self) -> FakeHTTPResponse:
        return self.response

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def reset_fake_connection(monkeypatch):
    FakeHTTPConnection.response = FakeHTTPResponse(200, {})
    FakeHTTPConnection.requests = []
    FakeHTTPConnection.fail_with = None
    monkeypatch.setattr("forge.models.ollama.HTTPConnection", FakeHTTPConnection)


def test_ollama_provider_reachable_check_returns_true() -> None:
    FakeHTTPConnection.response = FakeHTTPResponse(200, {"models": []})

    assert OllamaProvider("http://localhost:11434").is_running() is True


def test_ollama_provider_reachable_check_returns_false_on_error() -> None:
    FakeHTTPConnection.fail_with = OSError("connection refused")

    assert OllamaProvider("http://localhost:11434").is_running() is False


def test_list_models_parses_ollama_tags_response() -> None:
    FakeHTTPConnection.response = FakeHTTPResponse(
        200,
        {
            "models": [
                {"name": "llama3.1:8b", "size": 4_700_000_000, "modified_at": "2026-01-01"},
                {"name": "qwen2.5-coder:14b"},
                {"size": 1},
            ]
        },
    )

    models = OllamaProvider("http://localhost:11434").list_models()

    assert [model.name for model in models] == ["llama3.1:8b", "qwen2.5-coder:14b"]
    assert models[0].provider == "ollama"
    assert "4.7 GB" in (models[0].details or "")


def test_ask_sends_generate_payload_and_uses_configured_timeout() -> None:
    FakeHTTPConnection.response = FakeHTTPResponse(200, {"response": "Hello"})
    provider = OllamaProvider("http://localhost:11434", timeout_seconds=120)

    response = provider.ask("Explain dependency injection.", "llama3.1:8b")

    request = FakeHTTPConnection.requests[0]
    assert response.content == "Hello"
    assert request["timeout"] == 120
    assert request["method"] == "POST"
    assert request["path"] == "/api/generate"
    assert request["body"] == {
        "model": "llama3.1:8b",
        "prompt": "Explain dependency injection.",
        "stream": False,
    }


def test_ask_timeout_override_replaces_provider_timeout() -> None:
    FakeHTTPConnection.response = FakeHTTPResponse(200, {"response": "Hello"})
    provider = OllamaProvider("http://localhost:11434", timeout_seconds=120)

    provider.ask("Hello", "llama3.1:8b", timeout_seconds=240)

    assert FakeHTTPConnection.requests[0]["timeout"] == 240


def test_provider_formats_http_errors() -> None:
    FakeHTTPConnection.response = FakeHTTPResponse(
        404,
        {"error": "model 'missing:latest' not found"},
    )
    provider = OllamaProvider("http://localhost:11434")

    with pytest.raises(ModelProviderError) as exc_info:
        provider.ask("Hello", "missing:latest")

    message = str(exc_info.value)
    assert "Ollama returned HTTP 404" in message
    assert "missing:latest" in message
