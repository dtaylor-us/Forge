"""Data models for the Engineering Workflow Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class WorkflowTemplate(StrEnum):
    feature = "feature"
    bugfix = "bugfix"
    refactor = "refactor"
    custom = "custom"


class WorkflowStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class WorkflowStageStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    skipped = "skipped"
    failed = "failed"


@dataclass
class WorkflowStage:
    """One step within a workflow run."""

    name: str
    description: str
    service: str
    status: WorkflowStageStatus = WorkflowStageStatus.pending
    started_at: datetime | None = None
    completed_at: datetime | None = None
    artifact_refs: list[str] = field(default_factory=list)
    error: str | None = None
    output: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "service": self.service,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "artifact_refs": self.artifact_refs,
            "error": self.error,
        }


@dataclass
class WorkflowRun:
    """Execution record for one workflow run."""

    id: str
    template: WorkflowTemplate
    task: str
    repository: str
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    completed_at: datetime | None = None
    status: WorkflowStatus = WorkflowStatus.pending
    stages: list[WorkflowStage] = field(default_factory=list)
    workset_name: str | None = None
    patch_path: str | None = None
    verification_status: str | None = None
    policy_status: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "template": self.template.value,
            "task": self.task,
            "repository": self.repository,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "workset_name": self.workset_name,
            "patch_path": self.patch_path,
            "verification_status": self.verification_status,
            "policy_status": self.policy_status,
            "stages": [stage.to_dict() for stage in self.stages],
            "artifacts": self.artifacts,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class WorkflowDefinition:
    """Static description of a workflow template."""

    template: WorkflowTemplate
    name: str
    description: str
    stage_names: tuple[str, ...]
    output_artifact_types: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template.value,
            "name": self.name,
            "description": self.description,
            "stages": list(self.stage_names),
            "output_artifact_types": list(self.output_artifact_types),
        }
