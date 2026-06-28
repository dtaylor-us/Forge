"""Planning application service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.models.manager import ModelManager
from forge.planning import generate_plan
from forge.planning.store import save_plan
from forge.project.paths import ForgePaths


def generate(
    root: Path,
    task: str,
    workset: str,
    *,
    model: str | None = None,
    save: bool = False,
    use_memory: bool = True,
    timeout_seconds: int | None = None,
    model_manager: ModelManager | None = None,
) -> dict[str, Any]:
    """Generate an implementation plan without modifying source files."""
    plan = generate_plan(
        root,
        task,
        workset,
        model=model,
        timeout_seconds=timeout_seconds,
        model_manager=model_manager,
        save_to_memory=use_memory,
    )
    if save:
        plan.saved_path = save_plan(plan, ForgePaths.from_root(root).project_forge_dir)
    return {
        "task": plan.task,
        "workset": plan.workset_name,
        "model": plan.model,
        "generated_at": plan.generated_at.isoformat(),
        "content": plan.content,
        "saved_path": str(plan.saved_path) if plan.saved_path else None,
        "memory_used": use_memory,
        "memory_item_id": plan.memory_item_id,
    }
