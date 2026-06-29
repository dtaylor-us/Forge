"""Workflow Engine — pure orchestration of existing application services.

This module contains no business logic. Each stage calls exactly one
application service and records the outcome into the WorkflowRun.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge.workflows.models import (
    WorkflowRun,
    WorkflowStage,
    WorkflowStageStatus,
    WorkflowStatus,
    WorkflowTemplate,
)
from forge.workflows.registry import WorkflowRegistry


class WorkflowEngineError(Exception):
    """Raised when workflow infrastructure itself fails (not a stage failure)."""


class WorkflowEngine:
    """Orchestrate existing application services into a guided engineering workflow.

    The engine owns no business logic. Every stage delegates to an existing
    service. If a stage fails the run is marked failed and remaining stages
    are skipped, but all produced artifacts are preserved.
    """

    def __init__(
        self,
        root: Path,
        *,
        registry: WorkflowRegistry | None = None,
        model: str | None = None,
        model_manager: Any = None,
    ) -> None:
        self._root = root
        self._registry = registry or WorkflowRegistry.from_root(root)
        self._model = model
        self._model_manager = model_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, template: WorkflowTemplate, task: str) -> WorkflowRun:
        """Execute a complete workflow run and return the final WorkflowRun."""
        run = self._create_run(template, task)
        self._registry.save(run)

        stages = [
            ("repository", "Detect repository", "RepositoryService", self._stage_repository),
            ("workset", "Create workset", "WorksetService", self._stage_workset),
            ("context", "Generate context", "WorksetService", self._stage_context),
            ("plan", "Generate plan", "PlanningService", self._stage_plan),
            ("patch", "Generate patch", "ImplementationService", self._stage_patch),
            ("validate", "Validate patch", "PatchService", self._stage_validate),
            ("verify", "Run verification", "VerificationService", self._stage_verify),
            ("policy", "Evaluate policy", "PolicyService", self._stage_policy),
        ]

        run.status = WorkflowStatus.running
        self._registry.save(run)

        for stage_name, description, service, fn in stages:
            stage = WorkflowStage(
                name=stage_name,
                description=description,
                service=service,
            )
            run.stages.append(stage)
            self._execute_stage(run, stage, fn)
            self._registry.save(run)
            if stage.status == WorkflowStageStatus.failed:
                run.status = WorkflowStatus.failed
                run.completed_at = datetime.now(tz=UTC)
                self._registry.save(run)
                return run

        run.status = WorkflowStatus.completed
        run.completed_at = datetime.now(tz=UTC)
        self._registry.save(run)
        return run

    # ------------------------------------------------------------------
    # Stage implementations — each calls exactly one application service
    # ------------------------------------------------------------------

    def _stage_repository(self, run: WorkflowRun, stage: WorkflowStage) -> None:
        from forge.services import repository_service

        result = repository_service.detect(self._root)
        run.artifacts["repository"] = result
        stage.output = result

    def _stage_workset(self, run: WorkflowRun, stage: WorkflowStage) -> None:
        from forge.services import workset_service

        workset_name = _workset_name(run.id, run.template)
        result = workset_service.create(
            self._root,
            workset_name,
            run.task,
            max_results=20,
            force=True,
        )
        run.workset_name = workset_name
        run.artifacts["workset"] = result
        stage.output = result
        stage.artifact_refs.append(f"workset:{workset_name}")

    def _stage_context(self, run: WorkflowRun, stage: WorkflowStage) -> None:
        from forge.services import workset_service

        if not run.workset_name:
            raise WorkflowEngineError("workset stage must complete before context stage")
        result = workset_service.generate_context(self._root, run.workset_name)
        run.artifacts["context"] = result
        stage.output = {"file_count": result.get("file_count"), "path": result.get("path")}
        if result.get("path"):
            stage.artifact_refs.append(f"context_bundle:{result['path']}")

    def _stage_plan(self, run: WorkflowRun, stage: WorkflowStage) -> None:
        from forge.services import planning_service

        if not run.workset_name:
            raise WorkflowEngineError("workset stage must complete before plan stage")
        result = planning_service.generate(
            self._root,
            run.task,
            run.workset_name,
            model=self._model,
            save=True,
            model_manager=self._model_manager,
        )
        run.artifacts["plan"] = result
        stage.output = {
            "saved_path": result.get("saved_path"),
            "model": result.get("model"),
        }
        if result.get("saved_path"):
            stage.artifact_refs.append(f"implementation_plan:{result['saved_path']}")

    def _stage_patch(self, run: WorkflowRun, stage: WorkflowStage) -> None:
        from forge.services.implementation_service import ImplementationService

        if not run.workset_name:
            raise WorkflowEngineError("workset stage must complete before patch stage")
        svc = ImplementationService(model_manager=self._model_manager)
        impl = svc.implement(
            self._root,
            run.task,
            run.workset_name,
            model=self._model,
        )
        result = impl.to_dict()
        run.artifacts["patch"] = result
        if impl.patch_path:
            run.patch_path = str(impl.patch_path)
            stage.artifact_refs.append(f"patch:{impl.patch_name}")
        if not impl.valid:
            raise WorkflowEngineError(
                f"Patch generation produced an invalid patch: {'; '.join(impl.validation_errors)}"
            )
        stage.output = {
            "patch_path": result.get("patch_path"),
            "patch_name": result.get("patch_name"),
            "affected_files": result.get("affected_files"),
        }

    def _stage_validate(self, run: WorkflowRun, stage: WorkflowStage) -> None:
        from forge.services import patch_service

        patch_info = run.artifacts.get("patch", {})
        patch_name = patch_info.get("patch_name")
        if not patch_name:
            raise WorkflowEngineError("No patch name available for validation")
        result = patch_service.validate(self._root, patch_name)
        run.artifacts["validation"] = result
        stage.output = result
        if not result.get("valid"):
            errors = "; ".join(result.get("validation_errors", []))
            raise WorkflowEngineError(f"Patch validation failed: {errors}")

    def _stage_verify(self, run: WorkflowRun, stage: WorkflowStage) -> None:
        from forge.services import verification_service

        patch_name = (run.artifacts.get("patch") or {}).get("patch_name")
        try:
            result = verification_service.run(
                self._root,
                patch=patch_name,
                workset=run.workset_name,
            )
        except verification_service.VerificationServiceError as exc:
            raise WorkflowEngineError(f"Verification infrastructure error: {exc}") from exc
        run.artifacts["verification"] = result
        run.verification_status = str(result.get("overall_status", "unknown"))
        stage.output = {
            "overall_status": result.get("overall_status"),
            "summary": result.get("summary"),
        }

    def _stage_policy(self, run: WorkflowRun, stage: WorkflowStage) -> None:
        from forge.services import policy_service

        patch_info = run.artifacts.get("patch", {})
        patch_name = patch_info.get("patch_name")
        if not patch_name:
            raise WorkflowEngineError("No patch name available for policy evaluation")
        result = policy_service.check(self._root, patch_name)
        run.artifacts["policy"] = result
        evaluation = result.get("evaluation", {})
        run.policy_status = evaluation.get("status", "unknown")
        stage.output = {
            "status": evaluation.get("status"),
            "checks": evaluation.get("checks"),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_run(self, template: WorkflowTemplate, task: str) -> WorkflowRun:
        run_id = _run_id()
        return WorkflowRun(
            id=run_id,
            template=template,
            task=task,
            repository=str(self._root),
        )

    def _execute_stage(
        self,
        run: WorkflowRun,
        stage: WorkflowStage,
        fn: Any,
    ) -> None:
        stage.status = WorkflowStageStatus.running
        stage.started_at = datetime.now(tz=UTC)
        try:
            fn(run, stage)
            stage.status = WorkflowStageStatus.completed
        except Exception as exc:  # noqa: BLE001
            stage.status = WorkflowStageStatus.failed
            stage.error = str(exc)
        finally:
            stage.completed_at = datetime.now(tz=UTC)


def _run_id() -> str:
    return uuid.uuid4().hex[:16]


def _workset_name(run_id: str, template: WorkflowTemplate) -> str:
    return f"workflow-{template.value}-{run_id[:8]}"
