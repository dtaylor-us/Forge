"""Models for repository verification strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class VerificationEcosystem(StrEnum):
    """Supported verification ecosystems."""

    python = "python"
    node = "node"
    maven = "maven"
    gradle = "gradle"
    go = "go"
    rust = "rust"
    dotnet = "dotnet"
    unknown = "unknown"


class VerificationConfidence(StrEnum):
    """Confidence level for a detected verification strategy."""

    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class VerificationTool(StrEnum):
    """Known verification tools."""

    pytest = "pytest"
    ruff = "ruff"
    black = "black"
    npm = "npm"
    pnpm = "pnpm"
    yarn = "yarn"
    maven = "maven"
    gradle = "gradle"
    go = "go"
    cargo = "cargo"
    dotnet = "dotnet"


@dataclass(frozen=True)
class VerificationStep:
    """A verification step that may be executed by a future phase.

    ``required`` controls whether a failing step fails the overall
    verification result. Formatter checks like ``black --check`` are
    notoriously sensitive to local tool-version/target-version mismatches and
    can produce false FAILs unrelated to the actual change being verified, so
    they default to non-required ("soft") in ``_detect_python``. All other
    steps default to required, preserving prior behavior.
    """

    name: str
    command: str
    kind: str
    tool: VerificationTool | str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "name": self.name,
            "command": self.command,
            "kind": self.kind,
            "tool": self.tool.value if isinstance(self.tool, VerificationTool) else self.tool,
            "required": self.required,
        }


@dataclass(frozen=True)
class VerificationStrategy:
    """Detected verification strategy for a repository."""

    ecosystem: VerificationEcosystem
    confidence: VerificationConfidence
    package_manager: str | None = None
    steps: list[VerificationStep] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)

    def steps_for_kind(self, kind: str) -> list[VerificationStep]:
        """Return steps matching a verification kind."""
        return [step for step in self.steps if step.kind == kind]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "ecosystem": self.ecosystem.value,
            "confidence": self.confidence.value,
            "package_manager": self.package_manager,
            "steps": [step.to_dict() for step in self.steps],
            "signals": self.signals,
        }


@dataclass(frozen=True)
class VerificationRequest:
    """Request to detect repository verification strategy."""

    root: Path


@dataclass(frozen=True)
class VerificationResult:
    """Result of verification strategy detection."""

    root: Path
    strategy: VerificationStrategy
    executed: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "root": str(self.root),
            "executed": self.executed,
            "strategy": self.strategy.to_dict(),
        }
