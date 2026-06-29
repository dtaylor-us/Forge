"""Provider-independent orchestration for Engineering Execution."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from forge.execution.models import (
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStageResult,
    ExecutionStatus,
)
from forge.execution.stages import Stage, default_execution_stages


class ExecutionOrchestrator:
    """
    Coordinate execution stages without invoking providers or mutating repos.

    Stages receive and return an ExecutionContext, which lets future execution
    capabilities plug into the pipeline without changing the orchestrator.
    """

    def __init__(self, stages: Iterable[Stage] | None = None) -> None:
        self._stages = list(stages) if stages is not None else default_execution_stages()

    @property
    def stages(self) -> list[Stage]:
        """Return the configured execution stages in order."""

        return list(self._stages)

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        """Run the configured execution stages and return a structured result."""

        started_at = datetime.now(tz=UTC)
        context = ExecutionContext.from_request(request)
        request.status = ExecutionStatus.running
        stage_results: list[ExecutionStageResult] = []
        errors: list[str] = []

        for stage in self._stages:
            stage_started_at = datetime.now(tz=UTC)
            try:
                context = stage.run(context)
            except Exception as exc:
                stage_completed_at = datetime.now(tz=UTC)
                error = str(exc)
                errors.append(error)
                stage_results.append(
                    ExecutionStageResult(
                        name=stage.name,
                        started_at=stage_started_at,
                        completed_at=stage_completed_at,
                        status=ExecutionStatus.failed,
                        metadata={},
                        error=error,
                        duration=(stage_completed_at - stage_started_at).total_seconds(),
                    )
                )
                completed_at = datetime.now(tz=UTC)
                request.status = ExecutionStatus.failed
                return ExecutionResult(
                    status=ExecutionStatus.failed,
                    request=request,
                    context=context,
                    stages=stage_results,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration=(completed_at - started_at).total_seconds(),
                    summary="Execution pipeline failed.",
                    errors=errors,
                )

            stage_completed_at = datetime.now(tz=UTC)
            stage_results.append(
                ExecutionStageResult(
                    name=stage.name,
                    started_at=stage_started_at,
                    completed_at=stage_completed_at,
                    status=ExecutionStatus.completed,
                    metadata=dict(context.metadata),
                    duration=(stage_completed_at - stage_started_at).total_seconds(),
                )
            )

        completed_at = datetime.now(tz=UTC)
        request.status = ExecutionStatus.completed
        return ExecutionResult(
            status=ExecutionStatus.completed,
            request=request,
            context=context,
            stages=stage_results,
            started_at=started_at,
            completed_at=completed_at,
            duration=(completed_at - started_at).total_seconds(),
            summary="Execution pipeline completed.",
        )

