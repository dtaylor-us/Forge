"""Runtime configuration."""

from __future__ import annotations

import os
from enum import StrEnum

from pydantic import BaseModel, Field


class ProviderName(StrEnum):
    """Supported model provider identifiers."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class Settings(BaseModel):
    """Forge settings loaded from the local environment."""

    provider: ProviderName = Field(default=ProviderName.OLLAMA)
    model: str = Field(default="llama3.1:8b")
    ollama_host: str = Field(default="http://localhost:11434")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    anthropic_base_url: str = Field(default="https://api.anthropic.com/v1")
    max_tokens: int = Field(default=1024)
    openai_api_key: str | None = Field(default=None)
    anthropic_api_key: str | None = Field(default=None)

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from FORGE_* and provider-specific environment variables."""
        return cls(
            provider=os.getenv("FORGE_PROVIDER", ProviderName.OLLAMA.value),
            model=os.getenv("FORGE_MODEL", "llama3.1:8b"),
            ollama_host=os.getenv("FORGE_OLLAMA_HOST", "http://localhost:11434"),
            openai_base_url=os.getenv("FORGE_OPENAI_BASE_URL", "https://api.openai.com/v1"),
            anthropic_base_url=os.getenv(
                "FORGE_ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"
            ),
            max_tokens=int(os.getenv("FORGE_MAX_TOKENS", "1024")),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
