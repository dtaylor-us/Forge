"""Serializable verification report models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from forge.verification.models import VerificationStrategy


class VerificationStatus(StrEnum):
    """Status values for verification evidence."""

    pass_ = "pass"
    fail = "fail"
    skipped = "skipped"
    error = "error"


@dataclass(frozen=True)
class VerificationStepResult:
    """Result for one executed verification tool."""

    tool: str
    command: str
    working_directory: Path
    started_at: str
    completed_at: str
    duration: float
    exit_code: int | None
    stdout: str
    stderr: str
    status: VerificationStatus
    timed_out: bool = False
    exception: str | None = None
    kind: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "tool": self.tool,
            "command": self.command,
            "working_directory": str(self.working_directory),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.duration,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "status": self.status.value,
            "timed_out": self.timed_out,
            "exception": self.exception,
            "kind": self.kind,
            "name": self.name,
        }


@dataclass(frozen=True)
class VerificationArtifactMetadata:
    """Metadata for a persisted verification report artifact."""

    path: Path | None = None
    relative_path: str | None = None
    artifact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "path": str(self.path) if self.path else None,
            "relative_path": self.relative_path,
            "artifact_id": self.artifact_id,
        }


@dataclass(frozen=True)
class VerificationReport:
    """Structured engineering verification evidence."""

    repository: dict[str, Any]
    strategy: VerificationStrategy
    steps: list[VerificationStepResult]
    summary: dict[str, Any]
    duration: float
    overall_status: VerificationStatus
    recommendations: list[str] = field(default_factory=list)
    artifact: VerificationArtifactMetadata = field(default_factory=VerificationArtifactMetadata)
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_artifact(self, artifact: VerificationArtifactMetadata) -> VerificationReport:
        """Return a report copy with artifact metadata attached."""
        return VerificationReport(
            repository=self.repository,
            strategy=self.strategy,
            steps=self.steps,
            summary=self.summary,
            duration=self.duration,
            overall_status=self.overall_status,
            recommendations=self.recommendations,
            artifact=artifact,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "repository": self.repository,
            "strategy": self.strategy.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "summary": self.summary,
            "duration": self.duration,
            "overall_status": self.overall_status.value,
            "recommendations": self.recommendations,
            "artifact": self.artifact.to_dict(),
            "metadata": self.metadata,
        }
