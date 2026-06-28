"""Anthropic model provider."""

from __future__ import annotations

import json
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlparse

from forge.models.errors import ModelProviderError
from forge.models.types import ModelInfo, ModelResponse


class AnthropicProvider:
    """Anthropic provider behind the shared interface."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.anthropic.com/v1",
        max_tokens: int = 1024,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.endpoint = self.base_url
        self.max_tokens = max_tokens

    def list_models(self) -> list[ModelInfo]:
        payload = self._request("GET", "/models")
        models = payload.get("data", [])
        return [
            ModelInfo(
                name=str(model.get("id")),
                provider=self.name,
                details=str(model.get("display_name")) if model.get("display_name") else None,
            )
            for model in models
            if model.get("id")
        ]

    def ask(self, prompt: str, model: str) -> ModelResponse:
        payload = self._request(
            "POST",
            "/messages",
            {
                "model": model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        return ModelResponse(
            content=_extract_message_text(payload), model=model, provider=self.name
        )

    def _require_configured(self) -> None:
        if not self.api_key:
            raise ModelProviderError("ANTHROPIC_API_KEY is required when FORGE_PROVIDER=anthropic.")

    def normalize_model_name(self, model: str) -> str:
        """Return Anthropic's canonical model identifier."""
        return model

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._require_configured()
        parsed = urlparse(self.base_url)
        connection_cls = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        request_path = f"{parsed.path.rstrip('/')}{path}" if parsed.path else path
        encoded_body = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "x-api-key": str(self.api_key),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        try:
            connection = connection_cls(
                parsed.hostname or "api.anthropic.com", parsed.port, timeout=30
            )
            connection.request(method, request_path, body=encoded_body, headers=headers)
            response = connection.getresponse()
            data = response.read().decode("utf-8")
        except OSError as exc:
            raise ModelProviderError(
                f"Unable to reach Anthropic at {self.base_url}: {exc}"
            ) from exc
        finally:
            if "connection" in locals():
                connection.close()

        if response.status >= 400:
            raise ModelProviderError(f"Anthropic returned HTTP {response.status}: {data}")
        try:
            loaded = json.loads(data or "{}")
        except json.JSONDecodeError as exc:
            raise ModelProviderError("Anthropic returned invalid JSON.") from exc
        if not isinstance(loaded, dict):
            raise ModelProviderError("Anthropic returned an unexpected JSON payload.")
        return loaded


def _extract_message_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        raise ModelProviderError("Anthropic response did not include content.")
    text_parts = [
        item["text"]
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    ]
    if not text_parts:
        raise ModelProviderError("Anthropic response did not include text content.")
    return "\n".join(text_parts)
