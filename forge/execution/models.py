"""Typed models for Engineering Execution orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from forge.context.bundle import ContextBundle
from forge.memory.search import MemorySearchResult
from forge.planning.planner import ImplementationPlan


class ExecutionStatus(StrEnum):
    """Lifecycle states shared by execution requests, stages, and results."""

    prepared = "prepared"
    running = "running"
    completed = "completed"
    blocked = "blocked"
    failed = "failed"
    skipped = "skipped"


class ExecutionStage(StrEnum):
    """Canonical read-only stages for the initial execution pipeline."""

    load_workset = "load_workset"
    load_context = "load_context"
    load_engineering_memory = "load_engineering_memory"
    load_implementation_plan = "load_implementation_plan"
    assemble_execution_context = "assemble_execution_context"
    execution_complete = "execution_complete"


@dataclass(frozen=True)
class ExecutionTarget:
    """Repository/workset scope for an execution run."""

    root: str
    workset_name: str


@dataclass
class ExecutionRequest:
    """
    Input contract for execution orchestration.

    Existing request-preparation callers may populate the prepared fields
    directly. The pipeline only requires root, task, and workset, then loads the
    remaining read-only context through stages.
    """

    task: str
    workset: str
    root: Path | None = None
    target: ExecutionTarget | None = None
    context_bundle: ContextBundle | None = None
    related_memory: list[MemorySearchResult] = field(default_factory=list)
    implementation_plan: ImplementationPlan | None = None
    selected_model: str | None = None
    prompt: str = ""
    plan_path: Path | None = None
    max_lines_per_file: int = 60
    include_full: bool = False
    max_memory_results: int = 5
    status: ExecutionStatus = ExecutionStatus.prepared
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.root is None and self.target is not None:
            self.root = Path(self.target.root)
        if self.target is None and self.root is not None:
            self.target = ExecutionTarget(root=str(self.root), workset_name=self.workset)


@dataclass
class ExecutionContext:
    """Mutable context passed between execution stages."""

    request: ExecutionRequest
    root: Path
    task: str
    workset: str
    workset_data: dict[str, Any] | None = None
    context_bundle: ContextBundle | None = None
    related_memory: list[MemorySearchResult] = field(default_factory=list)
    implementation_plan: ImplementationPlan | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_request(cls, request: ExecutionRequest) -> ExecutionContext:
        if request.root is None:
            raise ValueError("ExecutionRequest.root is required for pipeline execution.")
        return cls(
            request=request,
            root=Path(request.root),
            task=request.task,
            workset=request.workset,
            context_bundle=request.context_bundle,
            related_memory=list(request.related_memory),
            implementation_plan=request.implementation_plan,
            metadata=dict(request.metadata),
        )


@dataclass(frozen=True)
class ExecutionStageResult:
    """Result metadata captured for one execution stage."""

    name: str
    started_at: datetime
    completed_at: datetime
    status: ExecutionStatus
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration: float = 0.0


@dataclass
class ExecutionResult:
    """Final result for an execution pipeline run."""

    status: ExecutionStatus
    request: ExecutionRequest | None = None
    context: ExecutionContext | None = None
    stages: list[ExecutionStageResult] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration: float = 0.0
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

