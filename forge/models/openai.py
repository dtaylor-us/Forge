"""OpenAI model provider."""

from __future__ import annotations

import json
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlparse

from forge.models.errors import ModelProviderError
from forge.models.types import ModelInfo, ModelResponse


class OpenAIProvider:
    """OpenAI provider behind the shared interface."""

    name = "openai"

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.openai.com/v1",
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
            ModelInfo(name=str(model.get("id")), provider=self.name)
            for model in models
            if model.get("id")
        ]

    def ask(
        self,
        prompt: str,
        model: str,
        timeout_seconds: int | None = None,
    ) -> ModelResponse:
        payload = self._request(
            "POST",
            "/responses",
            {"model": model, "input": prompt, "max_output_tokens": self.max_tokens},
        )
        incomplete_details = payload.get("incomplete_details")
        truncated = (
            isinstance(incomplete_details, dict)
            and incomplete_details.get("reason") == "max_output_tokens"
        )
        return ModelResponse(
            content=_extract_response_text(payload),
            model=model,
            provider=self.name,
            truncated=truncated,
        )

    def _require_configured(self) -> None:
        if not self.api_key:
            raise ModelProviderError("OPENAI_API_KEY is required when FORGE_PROVIDER=openai.")

    def normalize_model_name(self, model: str) -> str:
        """Return OpenAI's canonical model identifier."""
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
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            connection = connection_cls(
                parsed.hostname or "api.openai.com", parsed.port, timeout=30
            )
            connection.request(method, request_path, body=encoded_body, headers=headers)
            response = connection.getresponse()
            data = response.read().decode("utf-8")
        except OSError as exc:
            raise ModelProviderError(f"Unable to reach OpenAI at {self.base_url}: {exc}") from exc
        finally:
            if "connection" in locals():
                connection.close()

        if response.status >= 400:
            raise ModelProviderError(f"OpenAI returned HTTP {response.status}: {data}")
        try:
            loaded = json.loads(data or "{}")
        except json.JSONDecodeError as exc:
            raise ModelProviderError("OpenAI returned invalid JSON.") from exc
        if not isinstance(loaded, dict):
            raise ModelProviderError("OpenAI returned an unexpected JSON payload.")
        return loaded


def _extract_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text

    output = payload.get("output")
    if isinstance(output, list):
        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                    text_parts.append(content_item["text"])
        if text_parts:
            return "\n".join(text_parts)

    raise ModelProviderError("OpenAI response did not include text output.")
