"""Forge configuration file management."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forge.config.settings import ProviderName


def default_config_path() -> Path:
    """Return the user's Forge configuration path."""
    return Path.home() / ".forge" / "config.yaml"


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for one model provider."""

    endpoint: str | None = None
    timeout_seconds: int | None = None
    max_tokens: int | None = None
    """Output length cap. Anthropic/OpenAI: passed as max_tokens /
    max_output_tokens. Ollama: passed as the num_predict generation option."""
    context_window: int | None = None
    """Ollama-only: the num_ctx generation option. Ollama's server-side
    default (commonly 2048 regardless of what the model itself supports)
    silently truncates large prompts; this lets a project override it.
    Ignored by Anthropic/OpenAI, which manage context automatically."""


@dataclass(frozen=True)
class ForgeConfig:
    """User-editable Forge configuration."""

    provider: ProviderName = ProviderName.OLLAMA
    default_model: str = "llama3.1:8b"
    providers: dict[str, ProviderConfig] = field(
        default_factory=lambda: {
            ProviderName.OLLAMA.value: ProviderConfig(
                endpoint="http://localhost:11434",
                timeout_seconds=120,
                max_tokens=4096,
                context_window=8192,
            )
        }
    )


class ConfigManager:
    """Load, save, and edit Forge's local configuration."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()

    def load(self) -> ForgeConfig:
        """Load configuration, creating the default file when it is missing."""
        if not self.path.exists():
            config = ForgeConfig()
            self.save(config)
            return config
        data = _parse_simple_yaml(self.path.read_text(encoding="utf-8"))
        return self._config_from_mapping(data)

    def save(self, config: ForgeConfig) -> None:
        """Persist configuration to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(_render_config(config), encoding="utf-8")

    def show(self) -> str:
        """Return the current configuration file content."""
        self.load()
        return self.path.read_text(encoding="utf-8")

    def edit(self) -> Path:
        """Open the configuration in the user's editor and return its path."""
        self.load()
        editor = os.getenv("EDITOR") or os.getenv("VISUAL")
        if editor:
            subprocess.run([editor, str(self.path)], check=False)
        return self.path

    def set_default_model(self, model: str) -> ForgeConfig:
        """Set and save the configured default model."""
        config = self.load()
        updated = ForgeConfig(
            provider=config.provider,
            default_model=model,
            providers=config.providers,
        )
        self.save(updated)
        return updated

    def _config_from_mapping(self, data: dict[str, Any]) -> ForgeConfig:
        provider = ProviderName(str(data.get("provider") or ProviderName.OLLAMA.value))
        default_model = str(data.get("default_model") or "llama3.1:8b")
        providers = _provider_configs(data.get("providers"))
        if provider.value not in providers:
            providers[provider.value] = _default_provider_config(provider)
        return ForgeConfig(provider=provider, default_model=default_model, providers=providers)


def _default_provider_config(provider: ProviderName) -> ProviderConfig:
    if provider == ProviderName.OLLAMA:
        return ProviderConfig(
            endpoint="http://localhost:11434",
            timeout_seconds=120,
            max_tokens=4096,
            context_window=8192,
        )
    if provider == ProviderName.OPENAI:
        return ProviderConfig(endpoint="https://api.openai.com/v1", max_tokens=8192)
    if provider == ProviderName.ANTHROPIC:
        return ProviderConfig(endpoint="https://api.anthropic.com/v1", max_tokens=8192)
    return ProviderConfig()


def _provider_configs(value: object) -> dict[str, ProviderConfig]:
    if not isinstance(value, dict):
        return {
            ProviderName.OLLAMA.value: ProviderConfig(
                endpoint="http://localhost:11434",
                timeout_seconds=120,
                max_tokens=4096,
                context_window=8192,
            )
        }
    providers: dict[str, ProviderConfig] = {}
    for name, raw_config in value.items():
        provider_name = str(name)
        defaults = _provider_defaults_for_name(provider_name)
        if not isinstance(raw_config, dict):
            providers[provider_name] = defaults
            continue
        endpoint = raw_config.get("endpoint")
        timeout_seconds = _optional_positive_int(raw_config.get("timeout_seconds"))
        if timeout_seconds is None:
            timeout_seconds = defaults.timeout_seconds
        max_tokens = _optional_positive_int(raw_config.get("max_tokens"))
        if max_tokens is None:
            max_tokens = defaults.max_tokens
        context_window = _optional_positive_int(raw_config.get("context_window"))
        if context_window is None:
            context_window = defaults.context_window
        providers[provider_name] = ProviderConfig(
            endpoint=str(endpoint) if endpoint else defaults.endpoint,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            context_window=context_window,
        )
    return providers


def _provider_defaults_for_name(name: str) -> ProviderConfig:
    """Return the built-in defaults for a provider name found in a config file.

    Used to backfill ``max_tokens``/``context_window``/``timeout_seconds`` for
    existing ``~/.forge/config.yaml`` files written before these fields
    existed, so an upgrade doesn't silently fall back to ``None`` (which, for
    Anthropic/OpenAI, previously meant a hardcoded 1024-token cap baked into
    the provider class, and for Ollama meant the server's own often-too-small
    default context window).
    """
    try:
        provider = ProviderName(name)
    except ValueError:
        return ProviderConfig()
    return _default_provider_config(provider)


def _render_config(config: ForgeConfig) -> str:
    lines = [
        f"provider: {config.provider.value}",
        f"default_model: {config.default_model}",
        "providers:",
    ]
    for name, provider in config.providers.items():
        lines.append(f"  {name}:")
        if provider.endpoint:
            lines.append(f"    endpoint: {provider.endpoint}")
        if provider.timeout_seconds is not None:
            lines.append(f"    timeout_seconds: {provider.timeout_seconds}")
        if provider.max_tokens is not None:
            lines.append(f"    max_tokens: {provider.max_tokens}")
        if provider.context_window is not None:
            lines.append(f"    context_window: {provider.context_window}")
    return "\n".join(lines) + "\n"


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(str(value))
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def _parse_simple_yaml(content: str) -> dict[str, Any]:
    """Parse the small YAML subset Forge writes for its config file."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in content.splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        key, separator, value = line_without_comment.strip().partition(":")
        if not separator:
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        stripped_value = value.strip()
        if stripped_value:
            parent[key] = stripped_value.strip("\"'")
        else:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
    return root
