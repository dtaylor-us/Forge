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

    def __init__(
        self,
        host: str,
        timeout_seconds: int = 300,
        num_predict: int | None = None,
        context_window: int | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.endpoint = self.host
        self.timeout_seconds = timeout_seconds
        self.num_predict = num_predict
        self.context_window = context_window

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
        options: dict[str, int] = {}
        # Ollama's server-side default num_ctx (commonly 2048 regardless of
        # what the model itself supports) silently truncates large prompts —
        # the model never sees the end of the prompt, let alone has room to
        # finish a structured response. num_predict caps generation length the
        # same way max_tokens does for Anthropic/OpenAI. Both are omitted from
        # the request (left at Ollama's defaults) when not configured.
        if self.context_window is not None:
            options["num_ctx"] = self.context_window
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
        body: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if options:
            body["options"] = options
        payload = self._request(
            "POST",
            "/api/generate",
            body,
            timeout_seconds=timeout_seconds,
        )
        response = payload.get("response")
        if not isinstance(response, str):
            raise ModelProviderError("Ollama returned an invalid response payload.")
        # Ollama reports why generation stopped via `done_reason`: "stop" means
        # the model finished naturally; "length" means it was cut off by
        # num_predict or the context window filling up.
        done_reason = payload.get("done_reason")
        truncated = done_reason == "length"
        return ModelResponse(
            content=response, model=model, provider=self.name, truncated=truncated
        )

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
            msg = (
                "Ollama request timed out"
                f"{model_detail} at {self.host} after {configured_timeout} seconds. "
                "Try a smaller model or increase providers.ollama.timeout_seconds "
                "in ~/.forge/config.yaml."
            )
            if isinstance(model, str):
                smaller = self._smaller_models(model)
                if smaller:
                    msg += f" Smaller installed models you could try: {', '.join(smaller)}"
            raise ModelProviderError(msg) from exc
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

    def _list_models_quick(self, timeout: int = 5) -> list[str]:
        """Return installed model names; empty list on any error."""
        with suppress(Exception):
            payload = self._request("GET", "/api/tags", timeout_seconds=timeout)
            return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
        return []

    def _smaller_models(self, model: str) -> list[str]:
        """Return installed models with a smaller parameter count than the given model."""

        def _param_count(name: str) -> int | None:
            import re

            m = re.search(r"(\d+)b", name.lower())
            return int(m.group(1)) if m else None

        current = _param_count(model)
        if current is None:
            return []
        installed = self._list_models_quick()
        return [m for m in installed if (p := _param_count(m)) is not None and p < current]

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
