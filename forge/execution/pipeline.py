"""Canonical Engineering Execution pipeline entrypoints."""

from __future__ import annotations

from collections.abc import Iterable

from forge.execution.models import ExecutionRequest, ExecutionResult
from forge.execution.orchestrator import ExecutionOrchestrator
from forge.execution.stages import Stage, default_execution_stages


class ExecutionPipeline:
    """Reusable pipeline facade for Engineering Execution orchestration."""

    def __init__(self, stages: Iterable[Stage] | None = None) -> None:
        self._orchestrator = ExecutionOrchestrator(
            stages=list(stages) if stages is not None else default_execution_stages()
        )

    @property
    def stages(self) -> list[Stage]:
        """Return the configured stages in execution order."""

        return self._orchestrator.stages

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute the read-only pipeline for a prepared request."""

        return self._orchestrator.run(request)


def run_execution_pipeline(request: ExecutionRequest) -> ExecutionResult:
    """Run the default Engineering Execution pipeline."""

    return ExecutionPipeline().run(request)

