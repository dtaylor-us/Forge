"""Planning domain types and compatibility entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from forge.context.bundle import generate_bundle
from forge.models.manager import ModelManager


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
    memory_item_id: str | None = None


def generate_plan(
    root: Path,
    task: str,
    workset_name: str,
    *,
    model: str | None = None,
    timeout_seconds: int | None = None,
    max_lines_per_file: int = 60,
    include_full: bool = False,
    model_manager: ModelManager | None = None,
    save_to_memory: bool = True,
) -> ImplementationPlan:
    """
    Generate an implementation plan for task using a persisted workset.

    Automatically searches engineering memory for related prior work and
    includes it in the planning prompt. Saves the resulting plan to memory.

    Raises PlannerError for workset or model failures.
    """
    from forge.services.planning_service import PlanningService

    return PlanningService(
        model_manager=model_manager,
        bundle_factory=generate_bundle,
    ).generate_plan(
        root,
        task,
        workset_name,
        model=model,
        timeout_seconds=timeout_seconds,
        max_lines_per_file=max_lines_per_file,
        include_full=include_full,
        use_memory=True,
        save_to_memory=save_to_memory,
    )
