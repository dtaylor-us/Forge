"""Application service for generating reviewable implementation patches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge.execution import ExecutionService, ExecutionServiceError
from forge.execution.execution_prompt import build_implementation_prompt
from forge.models.manager import ModelManager
from forge.patches import (
    Patch,
    save_invalid_response,
    save_patch_content,
    validate_patch_content,
)
from forge.patches.service import inspect_patch
from forge.planning.planner import ImplementationPlan


@dataclass(frozen=True)
class ImplementationResult:
    """Result metadata for a generated implementation patch attempt."""

    task: str
    workset: str
    model: str
    status: str
    patch_path: Path | None
    valid: bool
    affected_files: list[str]
    validation_errors: list[str]
    patch_name: str | None
    show_target: str | None
    raw_response_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable result."""
        return {
            "task": self.task,
            "workset": self.workset,
            "model": self.model,
            "status": self.status,
            "patch_path": str(self.patch_path) if self.patch_path is not None else None,
            "patch_name": self.patch_name,
            "valid": self.valid,
            "affected_files": self.affected_files,
            "validation_errors": self.validation_errors,
            "raw_response_path": (
                str(self.raw_response_path) if self.raw_response_path is not None else None
            ),
            "next_command": (
                f"forge patch show {self.show_target}" if self.show_target is not None else None
            ),
        }


class ImplementationServiceError(Exception):
    """Raised when implementation patch generation cannot complete."""


class ImplementationService:
    """Generate reviewable patches without applying them."""

    def __init__(self, model_manager: ModelManager | None = None) -> None:
        self._model_manager = model_manager or ModelManager()
        self._execution_service = ExecutionService(self._model_manager)

    def implement(
        self,
        root: Path,
        task: str,
        workset: str,
        *,
        model: str | None = None,
        timeout_seconds: int | None = None,
        max_lines_per_file: int = 120,
        include_full: bool = False,
        output_path: Path | None = None,
    ) -> ImplementationResult:
        """Generate and store a model-produced unified diff."""
        selected_model = model or self._model_manager.config().default_model
        request = self._execution_service.create_request(
            root,
            task,
            workset,
            model=selected_model,
            implementation_plan=_default_implementation_plan(task, workset, selected_model),
            max_lines_per_file=max_lines_per_file,
            include_full=include_full,
        )
        if request.context_bundle is None or request.implementation_plan is None:
            raise ExecutionServiceError("Execution context was not prepared.")

        prompt = build_implementation_prompt(
            task,
            request.context_bundle,
            request.implementation_plan,
            request.selected_model or selected_model,
            request.related_memory,
        )
        request.prompt = prompt

        response = self._model_manager.ask(
            prompt=prompt,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        valid, errors, affected_files = validate_patch_content(response.content)

        if valid:
            patch = _save_valid_patch(root, response.content, output_path=output_path, task=task)
            return ImplementationResult(
                task=task,
                workset=workset,
                model=response.model,
                status="accepted",
                patch_path=patch.path,
                valid=patch.valid,
                affected_files=patch.affected_files,
                validation_errors=patch.validation_errors,
                patch_name=patch.name,
                show_target=_show_target(root, patch.path),
            )

        invalid_path = save_invalid_response(root, response.content, prefix=_artifact_slug(task))
        return ImplementationResult(
            task=task,
            workset=workset,
            model=response.model,
            status="rejected",
            patch_path=None,
            valid=False,
            affected_files=affected_files,
            validation_errors=errors,
            patch_name=None,
            show_target=None,
            raw_response_path=invalid_path,
        )


def _save_valid_patch(
    root: Path,
    content: str,
    *,
    output_path: Path | None,
    task: str,
) -> Patch:
    if output_path is None:
        return save_patch_content(root, content, prefix=_artifact_slug(task))
    path = output_path.expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    except OSError as exc:
        raise ImplementationServiceError(f"Unable to write patch to {path}: {exc}") from exc
    return inspect_patch(path)


def _default_implementation_plan(task: str, workset: str, model: str) -> ImplementationPlan:
    return ImplementationPlan(
        task=task,
        workset_name=workset,
        model=model,
        generated_at=datetime.now(tz=UTC),
        content=(
            "No saved implementation plan was provided. Generate the smallest reviewable "
            "patch that satisfies the task using the supplied workset context."
        ),
    )


def _show_target(root: Path, path: Path) -> str:
    default_patch_dir = root / ".forge" / "patches"
    try:
        if path.parent.resolve() == default_patch_dir.resolve():
            return path.name
    except OSError:
        pass
    return str(path)


def _artifact_slug(task: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in task)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:60] or "implement"
