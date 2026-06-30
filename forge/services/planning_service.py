"""Planning application service.

Application services own workflow coordination across deterministic domain
packages, provider abstractions, and project-local infrastructure. Planning is
the reference pattern for future execution, verification, patch, and
architecture services.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from forge.context.bundle import ContextBundle, generate_bundle
from forge.memory.manager import MemoryManager
from forge.memory.models import MemoryType
from forge.memory.search import search_memory
from forge.models.errors import ModelProviderError
from forge.models.manager import ModelManager, ModelNotFoundError
from forge.planning.planner import ImplementationPlan, PlannerError
from forge.planning.prompts import build_planning_prompt
from forge.planning.store import save_plan
from forge.project.paths import ForgePaths
from forge.worksets.store import WorksetStoreError


class PlanningService:
    """Coordinate implementation planning without modifying source files."""

    def __init__(
        self,
        model_manager: ModelManager | None = None,
        *,
        bundle_factory: Callable[..., ContextBundle] = generate_bundle,
    ) -> None:
        self._model_manager = model_manager
        self._bundle_factory = bundle_factory

    def generate_plan(
        self,
        root: Path,
        task: str,
        workset: str,
        *,
        model: str | None = None,
        save: bool = False,
        use_memory: bool = True,
        save_to_memory: bool | None = None,
        timeout_seconds: int | None = None,
        max_lines_per_file: int = 60,
        include_full: bool = False,
    ) -> ImplementationPlan:
        """Generate an implementation plan and optionally persist it."""
        manager = self._model_manager or ModelManager()

        try:
            bundle: ContextBundle = self._bundle_factory(
                root,
                workset,
                max_lines_per_file=max_lines_per_file,
                include_full=include_full,
            )
        except WorksetStoreError as exc:
            # WorksetStoreError messages already include "Workset '<name>' not
            # found." — re-wrapping with another "not found" prefix produced a
            # duplicated "not found: ... not found." message.
            raise PlannerError(str(exc)) from exc
        except Exception as exc:
            raise PlannerError(f"Failed to generate context bundle: {exc}") from exc

        config = manager.config()
        resolved_model = model or config.default_model

        memory_results = search_memory(root, task, max_results=5) if use_memory else []
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

        from datetime import UTC, datetime

        plan = ImplementationPlan(
            task=task,
            workset_name=workset,
            model=resolved_model,
            generated_at=datetime.now(tz=UTC),
            content=response.content,
        )

        should_save_memory = use_memory if save_to_memory is None else save_to_memory
        if should_save_memory:
            self._save_plan_memory(root, task, workset, bundle, memory_results, plan)

        if save:
            plan.saved_path = save_plan(plan, ForgePaths.from_root(root).project_forge_dir)

        return plan

    def generate_payload(
        self,
        root: Path,
        task: str,
        workset: str,
        *,
        model: str | None = None,
        save: bool = False,
        use_memory: bool = True,
        save_to_memory: bool | None = None,
        timeout_seconds: int | None = None,
        max_lines_per_file: int = 60,
        include_full: bool = False,
    ) -> dict[str, Any]:
        """Generate a serializable plan payload for adapters."""
        plan = self.generate_plan(
            root,
            task,
            workset,
            model=model,
            save=save,
            use_memory=use_memory,
            save_to_memory=save_to_memory,
            timeout_seconds=timeout_seconds,
            max_lines_per_file=max_lines_per_file,
            include_full=include_full,
        )
        return plan_payload(plan, memory_used=use_memory)

    def _save_plan_memory(
        self,
        root: Path,
        task: str,
        workset: str,
        bundle: ContextBundle,
        memory_results: list[Any],
        plan: ImplementationPlan,
    ) -> None:
        try:
            mem_manager = MemoryManager.from_root(root)
            related_files = [f.path for f in bundle.files]
            related_plans = [r.item.id for r in memory_results if r.item.type == MemoryType.plan]
            item = mem_manager.add(
                type=MemoryType.plan,
                title=task,
                repository=str(root),
                workset=workset,
                tags=_extract_tags(task, workset),
                summary=f"Implementation plan for: {task}",
                related_files=related_files,
                related_plans=related_plans,
                related_worksets=[workset],
            )
            plan.memory_item_id = item.id
        except Exception:
            pass


def plan_payload(plan: ImplementationPlan, *, memory_used: bool) -> dict[str, Any]:
    """Return a stable adapter payload for CLI/web/API callers."""
    return {
        "task": plan.task,
        "workset": plan.workset_name,
        "workset_name": plan.workset_name,
        "model": plan.model,
        "generated_at": plan.generated_at.isoformat(),
        "content": plan.content,
        "saved_path": str(plan.saved_path) if plan.saved_path else None,
        "memory_used": memory_used,
        "memory_item_id": plan.memory_item_id,
    }


def generate(
    root: Path,
    task: str,
    workset: str,
    *,
    model: str | None = None,
    save: bool = False,
    use_memory: bool = True,
    timeout_seconds: int | None = None,
    max_lines_per_file: int = 60,
    include_full: bool = False,
    model_manager: ModelManager | None = None,
) -> dict[str, Any]:
    """Generate a serializable implementation plan payload."""
    plan = PlanningService(model_manager=model_manager).generate_plan(
        root,
        task,
        workset,
        model=model,
        save=save,
        use_memory=True,
        save_to_memory=use_memory,
        timeout_seconds=timeout_seconds,
        max_lines_per_file=max_lines_per_file,
        include_full=include_full,
    )
    return plan_payload(plan, memory_used=use_memory)


def _extract_tags(task: str, workset: str) -> list[str]:
    import re

    tokens = re.findall(r"[a-zA-Z0-9]+", (task + " " + workset).lower())
    stop = {"a", "an", "the", "and", "or", "for", "to", "in", "of", "with", "on"}
    filtered = [t for t in tokens if t not in stop and len(t) > 2]
    return list(dict.fromkeys(filtered))[:10]
