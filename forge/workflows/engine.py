"""Workflow Engine — pure orchestration of existing application services.

This module contains no business logic. Each stage calls exactly one
application service and records the outcome into the WorkflowRun.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from contextlib import suppress
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
                self._cleanup_ephemeral_artifacts(run)
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
        include_tests = run.template == WorkflowTemplate.bugfix
        result = workset_service.create(
            self._root,
            workset_name,
            run.task,
            max_results=20,
            include_tests=include_tests,
            force=True,
            workflow=str(run.template),
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
            # Unattended workflow runs have no human in the loop to retry
            # `forge implement` by hand, unlike the CLI (which defaults to 1
            # and lets the user re-run). Give the repair loop more chances to
            # converge on a hunk a smaller/local model miscounted before the
            # whole run is marked failed.
            repair_attempts=3,
            # SEARCH/REPLACE is the default: the model only needs to copy
            # content verbatim (no line numbers), so hunk-header miscount
            # failures cannot occur.
            output_format="search_replace",
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
        from forge.git.service import GitService, GitServiceError
        from forge.patches.service import resolve_patch_path
        from forge.services import patch_service

        patch_info = run.artifacts.get("patch", {})
        patch_name = patch_info.get("patch_name")
        if not patch_name:
            raise WorkflowEngineError("No patch name available for validation")
        result = patch_service.validate(self._root, patch_name)
        run.artifacts["validation"] = result
        stage.output = result
        if not result.get("structural_valid", result.get("valid")):
            errors = "; ".join(result.get("validation_errors", []))
            raise WorkflowEngineError(
                f"Patch validation failed: {errors}\n\n"
                f"Next steps:\n"
                f"  inspect:    forge patch show {patch_name}\n"
                f'  regenerate: forge implement "<task>" --workset <workset>\n'
                f"  validate:   forge patch validate {patch_name}"
            )

        patch_path = resolve_patch_path(self._root, patch_name)
        git_svc = GitService(cwd=self._root)
        try:
            git_svc.apply_check(patch_path)
        except GitServiceError as exc:
            raise WorkflowEngineError(
                f"Patch does not apply cleanly to the working tree: {exc}\n\n"
                f"Next steps:\n"
                f"  inspect:    forge patch show {patch_name}\n"
                f'  regenerate: forge implement "<task>" --workset <workset>\n'
                f"  validate:   forge patch validate {patch_name}"
            ) from exc

    def _stage_verify(self, run: WorkflowRun, stage: WorkflowStage) -> None:
        """Run verification against the *patched* working tree.

        The patch is applied in a temporary git worktree so that:
        - Tests execute against the fixed code, not the pre-fix baseline.
        - The main working tree stays clean (no test artefacts left behind).

        If the worktree cannot be created the stage falls back to verifying
        the main working tree and notes the fallback in stage output.
        """
        from forge.git.service import GitService, GitServiceError
        from forge.patches.service import resolve_patch_path
        from forge.patches import PatchError
        from forge.project.paths import ForgePaths
        from forge.services import verification_service
        from forge.verification.executor import timestamp_slug

        patch_info = run.artifacts.get("patch") or {}
        patch_name = patch_info.get("patch_name")

        # Resolve patch path so we can apply it in the worktree.
        patch_path: Path | None = None
        if patch_name:
            with suppress(PatchError, Exception):
                patch_path = resolve_patch_path(self._root, patch_name)

        # Always write the report into the main project's verifications dir
        # so that forge apply / forge policy can find it via _latest_report().
        paths = ForgePaths.from_root(self._root)
        paths.verifications_dir.mkdir(parents=True, exist_ok=True)
        output_path = paths.verifications_dir / f"verification-{timestamp_slug()}.json"

        verify_root = self._root
        worktree_path: Path | None = None
        used_worktree = False

        if patch_path and patch_path.exists():
            git_svc = GitService(cwd=self._root)
            tmp = Path(tempfile.mkdtemp(prefix="forge-verify-"))
            try:
                git_svc.worktree_add(tmp)
                GitService(cwd=tmp).apply(patch_path)
                verify_root = tmp
                worktree_path = tmp
                used_worktree = True
            except (GitServiceError, Exception):
                # Worktree setup failed — fall back to main working tree.
                with suppress(Exception):
                    git_svc.worktree_remove(tmp)
                shutil.rmtree(tmp, ignore_errors=True)
                worktree_path = None
                verify_root = self._root

        try:
            result = verification_service.run(
                verify_root,
                output_path=output_path,
                patch=patch_name,
                workset=run.workset_name,
            )
        except verification_service.VerificationServiceError as exc:
            raise WorkflowEngineError(f"Verification infrastructure error: {exc}") from exc
        finally:
            if worktree_path:
                git_svc = GitService(cwd=self._root)
                with suppress(Exception):
                    git_svc.worktree_remove(worktree_path)
                shutil.rmtree(worktree_path, ignore_errors=True)

        run.artifacts["verification"] = result
        run.verification_status = str(result.get("overall_status", "unknown"))
        stage.output = {
            "overall_status": result.get("overall_status"),
            "summary": result.get("summary"),
            "verified_in_worktree": used_worktree,
        }

    def _cleanup_ephemeral_artifacts(self, run: WorkflowRun) -> None:
        """Delete the ephemeral workset and context bundle created for this run."""
        from forge.services import workset_service

        if run.workset_name:
            with suppress(Exception):
                workset_service.delete(self._root, run.workset_name)
        ctx_path = (run.artifacts.get("context") or {}).get("path")
        if ctx_path:
            with suppress(Exception):
                Path(ctx_path).unlink(missing_ok=True)

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
        # Fail the workflow stage when policy would block `forge apply`.
        # Without this, the workflow shows ✓ policy even though apply will refuse
        # the patch — leaving the user with a false "Patch ready" message.
        if evaluation.get("status") == "fail":
            failed = [
                c for c in (evaluation.get("checks") or [])
                if c.get("status") == "fail"
            ]
            details = "; ".join(c.get("message", c.get("name", "")) for c in failed)
            raise WorkflowEngineError(
                f"Policy evaluation failed — 'forge apply' will be blocked.\n"
                f"{details}\n\n"
                f"Run 'forge policy check {patch_name}' for the full report."
            )

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
