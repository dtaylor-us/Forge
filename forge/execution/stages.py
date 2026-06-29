"""Composable read-only stages for Engineering Execution."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from forge.context.bundle import ContextBundle, generate_bundle
from forge.execution.models import ExecutionContext, ExecutionStage
from forge.memory.search import MemorySearchResult, search_memory
from forge.planning.planner import ImplementationPlan
from forge.planning.store import plans_dir
from forge.worksets.store import load


class Stage(Protocol):
    """Common interface implemented by all execution stages."""

    name: str

    def run(self, context: ExecutionContext) -> ExecutionContext:
        """Perform read-only work and return the updated execution context."""


class LoadWorksetStage:
    """Load the persisted workset selected for execution."""

    name = ExecutionStage.load_workset.value

    def __init__(self, loader: Callable[[Path, str], dict[str, Any]] = load) -> None:
        self._loader = loader

    def run(self, context: ExecutionContext) -> ExecutionContext:
        context.workset_data = self._loader(context.root, context.workset)
        context.metadata["workset_file_count"] = len(context.workset_data.get("files", []))
        return context


class LoadContextStage:
    """Build the deterministic context bundle for the workset."""

    name = ExecutionStage.load_context.value

    def __init__(self, bundle_factory: Callable[..., ContextBundle] = generate_bundle) -> None:
        self._bundle_factory = bundle_factory

    def run(self, context: ExecutionContext) -> ExecutionContext:
        if context.context_bundle is None:
            request = context.request
            context.context_bundle = self._bundle_factory(
                context.root,
                context.workset,
                max_lines_per_file=request.max_lines_per_file,
                include_full=request.include_full,
            )
        context.metadata["context_file_count"] = len(context.context_bundle.files)
        context.metadata["context_total_tokens"] = context.context_bundle.total_tokens
        return context


class LoadEngineeringMemoryStage:
    """Load related Engineering Memory entries without mutating memory."""

    name = ExecutionStage.load_engineering_memory.value

    def __init__(
        self,
        memory_search: Callable[..., list[MemorySearchResult]] = search_memory,
    ) -> None:
        self._memory_search = memory_search

    def run(self, context: ExecutionContext) -> ExecutionContext:
        if not context.related_memory:
            context.related_memory = self._memory_search(
                context.root,
                context.task,
                max_results=context.request.max_memory_results,
            )
        context.metadata["memory_result_count"] = len(context.related_memory)
        return context


class LoadImplementationPlanStage:
    """Resolve the implementation plan that execution will coordinate."""

    name = ExecutionStage.load_implementation_plan.value

    def __init__(self, plan_loader: Callable[[Path], str] | None = None) -> None:
        self._plan_loader = plan_loader or _read_text

    def run(self, context: ExecutionContext) -> ExecutionContext:
        if context.implementation_plan is None:
            path = context.request.plan_path or _latest_saved_plan_path(
                context.root,
                context.workset,
            )
            if path is None:
                raise FileNotFoundError(
                    "No implementation plan found. Provide implementation_plan or plan_path, "
                    "or save a plan under .forge/plans/."
                )
            context.implementation_plan = _load_plan_file(
                path,
                task=context.task,
                workset=context.workset,
                model=context.request.selected_model or "unknown",
                reader=self._plan_loader,
            )
        context.metadata["plan_available"] = True
        context.metadata["plan_saved_path"] = (
            str(context.implementation_plan.saved_path)
            if context.implementation_plan.saved_path
            else None
        )
        return context


class AssembleExecutionContextStage:
    """Assemble stage outputs into the request contract for future phases."""

    name = ExecutionStage.assemble_execution_context.value

    def run(self, context: ExecutionContext) -> ExecutionContext:
        request = context.request
        request.context_bundle = context.context_bundle
        request.related_memory = list(context.related_memory)
        request.implementation_plan = context.implementation_plan
        request.metadata.update(context.metadata)
        context.metadata["execution_context_ready"] = True
        return context


class ExecutionCompleteStage:
    """Mark the read-only orchestration pass complete."""

    name = ExecutionStage.execution_complete.value

    def run(self, context: ExecutionContext) -> ExecutionContext:
        context.metadata["execution_complete"] = True
        return context


def default_execution_stages() -> list[Stage]:
    """Return the canonical read-only execution pipeline."""

    return [
        LoadWorksetStage(),
        LoadContextStage(),
        LoadEngineeringMemoryStage(),
        LoadImplementationPlanStage(),
        AssembleExecutionContextStage(),
        ExecutionCompleteStage(),
    ]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
    reader: Callable[[Path], str],
) -> ImplementationPlan:
    content = reader(path)
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
