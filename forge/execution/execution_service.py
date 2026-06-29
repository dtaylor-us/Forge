"""Engineering Execution application service."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from forge.context.bundle import ContextBundle, generate_bundle
from forge.execution.execution_models import ExecutionRequest, ExecutionTarget
from forge.execution.execution_prompt import build_execution_prompt
from forge.memory.models import MemoryType
from forge.memory.search import MemorySearchResult, search_memory
from forge.models.manager import ModelManager
from forge.planning.planner import ImplementationPlan
from forge.planning.store import plans_dir
from forge.worksets.store import WorksetStoreError


class ExecutionServiceError(Exception):
    """Raised when an execution request cannot be prepared."""


class ExecutionService:
    """
    Prepare Engineering Execution requests.

    This service intentionally performs orchestration only. It loads existing
    context, memory, and plan artifacts, then returns a structured request for
    future execution phases to consume.
    """

    def __init__(self, model_manager: ModelManager | None = None) -> None:
        self._model_manager = model_manager or ModelManager()

    def create_request(
        self,
        root: Path,
        task: str,
        workset: str,
        *,
        model: str | None = None,
        implementation_plan: ImplementationPlan | None = None,
        plan_path: Path | None = None,
        max_lines_per_file: int = 120,
        include_full: bool = False,
        max_memory_results: int = 5,
    ) -> ExecutionRequest:
        """Assemble an execution request without executing it."""
        try:
            bundle: ContextBundle = generate_bundle(
                root,
                workset,
                max_lines_per_file=max_lines_per_file,
                include_full=include_full,
            )
        except WorksetStoreError as exc:
            raise ExecutionServiceError(f"Workset {workset!r} not found: {exc}") from exc
        except Exception as exc:
            raise ExecutionServiceError(f"Failed to generate context bundle: {exc}") from exc

        related_memory = search_memory(root, task, max_results=max_memory_results)
        selected_model = model or self._model_manager.config().default_model
        plan = implementation_plan or self._load_plan(
            root,
            task,
            workset,
            selected_model,
            plan_path=plan_path,
            related_memory=related_memory,
        )
        prompt = build_execution_prompt(task, bundle, plan, selected_model, related_memory or None)

        return ExecutionRequest(
            task=task,
            workset=workset,
            target=ExecutionTarget(root=str(root), workset_name=workset),
            context_bundle=bundle,
            related_memory=related_memory,
            implementation_plan=plan,
            selected_model=selected_model,
            prompt=prompt,
        )

    def _load_plan(
        self,
        root: Path,
        task: str,
        workset: str,
        model: str,
        *,
        plan_path: Path | None,
        related_memory: list[MemorySearchResult],
    ) -> ImplementationPlan:
        if plan_path is not None:
            return _load_plan_file(plan_path, task=task, workset=workset, model=model)

        memory_plan = _latest_memory_plan(root, task, workset, related_memory, model)
        if memory_plan is not None:
            return memory_plan

        latest_path = _latest_saved_plan_path(root, workset)
        if latest_path is not None:
            return _load_plan_file(latest_path, task=task, workset=workset, model=model)

        raise ExecutionServiceError(
            "No implementation plan found. Provide an ImplementationPlan or plan_path, "
            "or save a plan under .forge/plans/ before preparing execution."
        )


def _latest_memory_plan(
    root: Path,
    task: str,
    workset: str,
    related_memory: list[MemorySearchResult],
    model: str,
) -> ImplementationPlan | None:
    candidates = [
        result.item
        for result in related_memory
        if result.item.type == MemoryType.plan and result.item.workset == workset
    ]
    candidates.sort(key=lambda item: item.created_at, reverse=True)
    for item in candidates:
        if item.source_path:
            path = root / item.source_path
            if path.exists():
                return _load_plan_file(path, task=task, workset=workset, model=model)
        if item.summary:
            return ImplementationPlan(
                task=task,
                workset_name=workset,
                model=model,
                generated_at=_parse_datetime(item.created_at),
                content=item.summary,
                memory_item_id=item.id,
            )
    return None


def _latest_saved_plan_path(root: Path, workset: str) -> Path | None:
    directory = plans_dir(root / ".forge")
    if not directory.exists():
        return None
    candidates = sorted(directory.glob(f"{workset}-*.md"), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def _load_plan_file(
    path: Path,
    *,
    task: str,
    workset: str,
    model: str,
) -> ImplementationPlan:
    if not path.exists():
        raise ExecutionServiceError(f"Implementation plan not found: {path}")
    content = path.read_text(encoding="utf-8")
    return ImplementationPlan(
        task=task,
        workset_name=_workset_from_plan_path(path) or workset,
        model=model,
        generated_at=_generated_at_from_plan_path(path),
        content=content,
        saved_path=path,
    )


def _workset_from_plan_path(path: Path) -> str | None:
    match = re.match(r"(.+)-\d{8}T\d{6}\.md$", path.name)
    return match.group(1) if match else None


def _generated_at_from_plan_path(path: Path) -> datetime:
    match = re.match(r".+-(\d{8}T\d{6})\.md$", path.name)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(tz=UTC)
