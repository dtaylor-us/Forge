"""Orchestrate plan generation: workset + context bundle + model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from forge.context.bundle import ContextBundle, generate_bundle
from forge.models.errors import ModelProviderError
from forge.models.manager import ModelManager, ModelNotFoundError
from forge.planning.prompts import build_planning_prompt
from forge.worksets.store import WorksetStoreError


class PlannerError(Exception):
    """Raised when planning cannot proceed."""


@dataclass
class ImplementationPlan:
    task: str
    workset_name: str
    model: str
    generated_at: datetime
    content: str
    saved_path: Path | None = None


def generate_plan(
    root: Path,
    task: str,
    workset_name: str,
    *,
    model: str | None = None,
    timeout_seconds: int | None = None,
    max_lines_per_file: int = 120,
    include_full: bool = False,
    model_manager: ModelManager | None = None,
) -> ImplementationPlan:
    """
    Generate an implementation plan for task using a persisted workset.

    Raises PlannerError for workset or model failures.
    """
    manager = model_manager or ModelManager()

    try:
        bundle: ContextBundle = generate_bundle(
            root,
            workset_name,
            max_lines_per_file=max_lines_per_file,
            include_full=include_full,
        )
    except WorksetStoreError as exc:
        raise PlannerError(f"Workset {workset_name!r} not found: {exc}") from exc
    except Exception as exc:
        raise PlannerError(f"Failed to generate context bundle: {exc}") from exc

    config = manager.config()
    resolved_model = model or config.default_model

    prompt = build_planning_prompt(task, bundle, resolved_model)

    try:
        response = manager.ask(
            prompt=prompt,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except ModelNotFoundError as exc:
        raise PlannerError(f"Model not found: {exc.requested_model}") from exc
    except ModelProviderError as exc:
        raise PlannerError(f"Model provider error: {exc}") from exc

    return ImplementationPlan(
        task=task,
        workset_name=workset_name,
        model=resolved_model,
        generated_at=datetime.now(tz=UTC),
        content=response.content,
    )
