"""Ollama model provider."""

from __future__ import annotations

import json
from contextlib import suppress
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlparse

from forge.models.errors import ModelProviderError
from forge.models.types import ModelInfo, ModelResponse


class OllamaProvider:
    """Model provider backed by a local Ollama server."""

    name = "ollama"

    def __init__(self, host: str, timeout_seconds: int = 120) -> None:
        self.host = host.rstrip("/")
        self.endpoint = self.host
        self.timeout_seconds = timeout_seconds

    def list_models(self) -> list[ModelInfo]:
        payload = self._request("GET", "/api/tags")
        models = payload.get("models", [])
        return [
            ModelInfo(
                name=str(model.get("name", "")),
                provider=self.name,
                details=self._format_details(model),
            )
            for model in models
            if model.get("name")
        ]

    def ask(
        self,
        prompt: str,
        model: str,
        timeout_seconds: int | None = None,
    ) -> ModelResponse:
        payload = self._request(
            "POST",
            "/api/generate",
            {"model": model, "prompt": prompt, "stream": False},
            timeout_seconds=timeout_seconds,
        )
        response = payload.get("response")
        if not isinstance(response, str):
            raise ModelProviderError("Ollama returned an invalid response payload.")
        return ModelResponse(content=response, model=model, provider=self.name)

    def is_running(self) -> bool:
        """Return whether the configured Ollama server responds."""
        try:
            self._request("GET", "/api/tags")
        except ModelProviderError:
            return False
        return True

    def normalize_model_name(self, model: str) -> str:
        """Return Ollama's canonical model identifier."""
        return model

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        parsed = urlparse(self.host)
        connection_cls = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        port = parsed.port
        netloc = parsed.hostname or "localhost"
        request_path = f"{parsed.path.rstrip('/')}{path}" if parsed.path else path
        encoded_body = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        configured_timeout = timeout_seconds or self.timeout_seconds

        try:
            connection = connection_cls(netloc, port=port, timeout=configured_timeout)
            connection.request(method, request_path, body=encoded_body, headers=headers)
            response = connection.getresponse()
            data = response.read().decode("utf-8")
        except TimeoutError as exc:
            model = body.get("model") if body else None
            model_detail = f" for model {model}" if isinstance(model, str) else ""
            raise ModelProviderError(
                "Ollama request timed out"
                f"{model_detail} at {self.host} after {configured_timeout} seconds. "
                "Try a smaller model or increase providers.ollama.timeout_seconds "
                "in ~/.forge/config.yaml."
            ) from exc
        except OSError as exc:
            raise ModelProviderError(f"Unable to reach Ollama at {self.host}: {exc}") from exc
        finally:
            with suppress(UnboundLocalError):
                connection.close()

        if response.status >= 400:
            raise ModelProviderError(f"Ollama returned HTTP {response.status}: {data}")
        try:
            loaded = json.loads(data or "{}")
        except json.JSONDecodeError as exc:
            raise ModelProviderError("Ollama returned invalid JSON.") from exc
        if not isinstance(loaded, dict):
            raise ModelProviderError("Ollama returned an unexpected JSON payload.")
        return loaded

    @staticmethod
    def _format_details(model: dict[str, Any]) -> str | None:
        size = model.get("size")
        modified = model.get("modified_at")
        parts = []
        if isinstance(size, int):
            parts.append(f"{size / 1_000_000_000:.1f} GB")
        if isinstance(modified, str):
            parts.append(f"modified {modified}")
        return ", ".join(parts) if parts else None
