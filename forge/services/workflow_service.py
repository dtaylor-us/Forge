"""Workflow application service — public orchestration entry point.

CLI and other callers should interact only with this module. The engine
and templates are internal workflow-package concerns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.workflows.engine import WorkflowEngine
from forge.workflows.models import WorkflowTemplate
from forge.workflows.registry import WorkflowRegistry
from forge.workflows.templates import ALL_DEFINITIONS


class WorkflowServiceError(Exception):
    """Raised when workflow execution cannot start or a stage fails fatally."""


def run_workflow(
    root: Path,
    template: str | WorkflowTemplate,
    task: str,
    *,
    model: str | None = None,
    model_manager: Any = None,
) -> dict[str, Any]:
    """Execute a workflow and return a serializable run payload."""
    try:
        resolved = WorkflowTemplate(template)
    except ValueError as exc:
        available = ", ".join(t.value for t in WorkflowTemplate)
        raise WorkflowServiceError(
            f"Unknown workflow template {template!r}. Available: {available}"
        ) from exc

    engine = WorkflowEngine(root, model=model, model_manager=model_manager)
    run = engine.run(resolved, task)
    return run.to_dict()


def list_templates() -> list[dict[str, Any]]:
    """Return all registered workflow template definitions."""
    return [definition.to_dict() for definition in ALL_DEFINITIONS.values()]


def list_runs(
    root: Path,
    *,
    template: str | WorkflowTemplate | None = None,
) -> list[dict[str, Any]]:
    """Return persisted workflow run summaries."""
    registry = WorkflowRegistry.from_root(root)
    resolved_template = WorkflowTemplate(template) if template else None
    return registry.list_runs(template=resolved_template)


def show_run(root: Path, run_id: str) -> dict[str, Any] | None:
    """Return a single workflow run record by ID."""
    return WorkflowRegistry.from_root(root).load(run_id)
