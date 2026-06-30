"""Application service for generating reviewable implementation patches."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge.execution import ExecutionService, ExecutionServiceError
from forge.execution.execution_prompt import (
    build_implementation_prompt,
    build_numbered_file_details,
    build_repair_prompt,
)
from forge.models.manager import ModelManager
from forge.patches import (
    Patch,
    apply_check_patch_content,
    realign_patch_hunk_headers,
    save_invalid_response,
    save_patch_content,
    validate_patch_content,
    verify_patch_context,
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
    test_warning: str | None = None
    repair_attempts_made: int = 0

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
            "test_warning": self.test_warning,
            "repair_attempts_made": self.repair_attempts_made,
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
        max_lines_per_file: int = 60,
        include_full: bool = True,
        output_path: Path | None = None,
        repair_attempts: int = 1,
    ) -> ImplementationResult:
        """Generate and store a model-produced unified diff, with optional repair.

        ``include_full`` defaults to True: patch generation requires the model to
        reproduce exact context lines from the real file, so excerpted/truncated
        content (the default for browsing-oriented commands) is not appropriate
        here. The context-verification step below independently catches any
        remaining mismatches between the model's diff and the file on disk.
        """
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

        prompt, test_warning = build_implementation_prompt(
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
        current_content = _strip_markdown_fence(response.content)
        # Deterministically correct miscounted hunk starting positions before
        # validation. git apply --recount (applied by GitService) fixes hunk
        # line *counts*, but it cannot fix a wrong starting *position* (L in
        # @@ -L,N @@). This pass searches the real file for the unique location
        # where each hunk's context/removed block appears and rewrites the header
        # when exactly one match is found, eliminating that failure class without
        # touching content the model got right.
        current_content, _ = realign_patch_hunk_headers(root, current_content)
        current_model = response.model
        attempts_made = 0

        valid, errors, affected_files = validate_patch_content(current_content)
        apply_ok, apply_error = _apply_check_if_structurally_valid(root, current_content, valid)
        is_valid = valid and apply_ok
        context_mismatches = [] if is_valid else verify_patch_context(root, current_content)

        file_details = _bundle_file_details(request.context_bundle)
        while not is_valid and attempts_made < repair_attempts:
            attempts_made += 1
            repair_prompt = build_repair_prompt(
                task=task,
                original_patch=current_content,
                structural_errors=errors,
                apply_check_error=apply_error,
                file_details=file_details,
                context_mismatches=context_mismatches,
            )
            repair_response = self._model_manager.ask(
                prompt=repair_prompt,
                model=model,
                timeout_seconds=timeout_seconds,
            )
            current_content = _strip_markdown_fence(repair_response.content)
            current_content, _ = realign_patch_hunk_headers(root, current_content)
            current_model = repair_response.model
            valid, errors, affected_files = validate_patch_content(current_content)
            apply_ok, apply_error = _apply_check_if_structurally_valid(
                root,
                current_content,
                valid,
            )
            is_valid = valid and apply_ok
            context_mismatches = [] if is_valid else verify_patch_context(root, current_content)

        if is_valid:
            patch = _save_valid_patch(root, current_content, output_path=output_path, task=task)
            return ImplementationResult(
                task=task,
                workset=workset,
                model=current_model,
                status="accepted",
                patch_path=patch.path,
                valid=patch.valid,
                affected_files=patch.affected_files,
                validation_errors=patch.validation_errors,
                patch_name=patch.name,
                show_target=_show_target(root, patch.path),
                test_warning=test_warning,
                repair_attempts_made=attempts_made,
            )

        if apply_error and apply_error not in errors:
            errors = [*errors, apply_error]
        if context_mismatches:
            # Surface the specific line-level diagnosis (patch expected X, file
            # actually has Y) on final failure, not just the raw, often-cryptic
            # `git apply` message (e.g. "corrupt patch at line 15"). This was
            # already computed to drive the repair prompt; previously it was
            # discarded once repair attempts ran out, leaving callers with
            # only the opaque git error.
            errors = [*errors, *[m for m in context_mismatches if m not in errors]]
        invalid_path = save_invalid_response(root, current_content, prefix=_artifact_slug(task))
        return ImplementationResult(
            task=task,
            workset=workset,
            model=current_model,
            status="rejected",
            patch_path=None,
            valid=False,
            affected_files=affected_files,
            validation_errors=errors,
            patch_name=None,
            show_target=None,
            raw_response_path=invalid_path,
            test_warning=test_warning,
            repair_attempts_made=attempts_made,
        )


def _strip_markdown_fence(content: str) -> str:
    """Extract raw diff from a markdown code fence if the model wrapped it."""
    stripped = content.strip()
    # Match ```diff, ```patch, or plain ``` opening fence
    match = re.match(r"^```(?:diff|patch)?\s*\n(.*?)```\s*$", stripped, re.DOTALL)
    if match:
        return match.group(1)
    return content


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


def _apply_check_if_structurally_valid(
    root: Path,
    content: str,
    structurally_valid: bool,
) -> tuple[bool, str]:
    if not structurally_valid:
        return False, "Structural validation failed"
    return apply_check_patch_content(root, content)


def _bundle_file_details(bundle: Any) -> str:
    """Extract detailed, line-numbered file context from a bundle for repair prompts.

    Uses the same "N| " gutter rendering as the initial implementation
    prompt (see ``build_numbered_file_details``) so the model has line-number
    ground truth on repair attempts too, instead of repeating the same
    miscounted hunk header it produced the first time.
    """
    return build_numbered_file_details(bundle)


def _artifact_slug(task: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in task)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:60] or "implement"
