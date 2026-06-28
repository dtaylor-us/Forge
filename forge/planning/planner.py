"""Orchestrate plan generation: workset + context bundle + model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from forge.context.bundle import ContextBundle, generate_bundle
from forge.memory.manager import MemoryManager
from forge.memory.models import MemoryType
from forge.memory.search import search_memory
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
    memory_item_id: str | None = None


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
    save_to_memory: bool = True,
) -> ImplementationPlan:
    """
    Generate an implementation plan for task using a persisted workset.

    Automatically searches engineering memory for related prior work and
    includes it in the planning prompt. Saves the resulting plan to memory.

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

    memory_results = search_memory(root, task, max_results=5)

    prompt = build_planning_prompt(task, bundle, resolved_model, memory_results or None)

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

    plan = ImplementationPlan(
        task=task,
        workset_name=workset_name,
        model=resolved_model,
        generated_at=datetime.now(tz=UTC),
        content=response.content,
    )

    if save_to_memory:
        try:
            mem_manager = MemoryManager.from_root(root)
            related_files = [f.path for f in bundle.files]
            related_plans = [r.item.id for r in memory_results if r.item.type == MemoryType.plan]
            item = mem_manager.add(
                type=MemoryType.plan,
                title=task,
                repository=str(root),
                workset=workset_name,
                tags=_extract_tags(task, workset_name),
                summary=f"Implementation plan for: {task}",
                related_files=related_files,
                related_plans=related_plans,
                related_worksets=[workset_name],
            )
            plan.memory_item_id = item.id
        except Exception:
            pass

    return plan


def _extract_tags(task: str, workset: str) -> list[str]:
    import re

    tokens = re.findall(r"[a-zA-Z0-9]+", (task + " " + workset).lower())
    stop = {"a", "an", "the", "and", "or", "for", "to", "in", "of", "with", "on"}
    filtered = [t for t in tokens if t not in stop and len(t) > 2]
    return list(dict.fromkeys(filtered))[:10]
