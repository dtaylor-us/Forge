"""Tests for Engineering Execution request preparation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from forge.execution import (
    ExecutionPipeline,
    ExecutionRequest,
    ExecutionService,
    ExecutionStage,
    ExecutionStatus,
)
from forge.execution.execution_prompt import build_execution_prompt
from forge.execution.models import ExecutionContext
from forge.memory.manager import MemoryManager
from forge.memory.models import MemoryType
from forge.planning.planner import ImplementationPlan
from forge.planning.store import save_plan
from forge.worksets.store import save

TASK = "Add timeout validation"
WORKSET_NAME = "model-config"


def _make_workset(tmp_path: Path, name: str = WORKSET_NAME) -> None:
    data = {
        "schema_version": 1,
        "name": name,
        "query": "model manager config timeout",
        "root": str(tmp_path),
        "created_at": "2026-06-28T00:00:00+00:00",
        "updated_at": "2026-06-28T00:00:00+00:00",
        "include_tests": False,
        "max_results": 10,
        "files": [
            {
                "path": "forge/models/manager.py",
                "score": 15,
                "category": "source",
                "reasons": [{"signal": "filename", "detail": "manager", "points": 15}],
                "manual": False,
            }
        ],
    }
    save(tmp_path, data)
    src = tmp_path / "forge" / "models" / "manager.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(
        "class ModelManager:\n"
        "    def ask(self, prompt, timeout_seconds=None):\n"
        "        return prompt\n",
        encoding="utf-8",
    )


def _make_plan(content: str = "# Forge Implementation Plan\n\n## Task\nAdd timeout validation"):
    return ImplementationPlan(
        task=TASK,
        workset_name=WORKSET_NAME,
        model="qwen2.5",
        generated_at=datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC),
        content=content,
    )


def _mock_model_manager(default_model: str = "qwen2.5"):
    manager = MagicMock()
    manager.config.return_value = MagicMock(default_model=default_model)
    return manager


def test_execution_request_creation(tmp_path):
    _make_workset(tmp_path)
    plan = _make_plan()
    service = ExecutionService(model_manager=_mock_model_manager())

    request = service.create_request(tmp_path, TASK, WORKSET_NAME, implementation_plan=plan)

    assert isinstance(request, ExecutionRequest)
    assert request.task == TASK
    assert request.workset == WORKSET_NAME
    assert request.target.root == str(tmp_path)
    assert request.status == ExecutionStatus.prepared
    assert request.implementation_plan == plan


def test_execution_prompt_generation_reuses_context_sections(tmp_path):
    _make_workset(tmp_path)
    request = ExecutionService(model_manager=_mock_model_manager()).create_request(
        tmp_path,
        TASK,
        WORKSET_NAME,
        implementation_plan=_make_plan(),
    )

    prompt = build_execution_prompt(
        TASK,
        request.context_bundle,
        request.implementation_plan,
        request.selected_model,
        request.related_memory,
    )

    assert "# Execution Request" in prompt
    assert "forge/models/manager.py" in prompt
    assert "ModelManager" in prompt
    assert "# Forge Implementation Plan" in prompt
    assert "Do NOT generate code patches or diffs" in prompt
    assert "No files were modified" in prompt


def test_execution_service_loads_memory(tmp_path):
    _make_workset(tmp_path)
    MemoryManager.from_root(tmp_path).add(
        type=MemoryType.decision,
        title="Timeout validation decision",
        repository=str(tmp_path),
        workset=WORKSET_NAME,
        tags=["timeout"],
        summary="Previous work chose explicit timeout validation.",
    )

    request = ExecutionService(model_manager=_mock_model_manager()).create_request(
        tmp_path,
        TASK,
        WORKSET_NAME,
        implementation_plan=_make_plan(),
    )

    assert request.related_memory
    assert request.related_memory[0].item.title == "Timeout validation decision"
    assert "Engineering Memory Context" in request.prompt
    assert "Previous work chose explicit timeout validation" in request.prompt


def test_execution_service_loads_plan_from_path(tmp_path):
    _make_workset(tmp_path)
    plan_path = save_plan(_make_plan("Saved plan content"), tmp_path / ".forge")

    request = ExecutionService(model_manager=_mock_model_manager()).create_request(
        tmp_path,
        TASK,
        WORKSET_NAME,
        plan_path=plan_path,
    )

    assert request.implementation_plan.saved_path == plan_path
    assert request.implementation_plan.content == "Saved plan content"
    assert "Saved plan content" in request.prompt


def test_execution_service_loads_latest_saved_plan(tmp_path):
    _make_workset(tmp_path)
    save_plan(_make_plan("Latest saved plan content"), tmp_path / ".forge")

    request = ExecutionService(model_manager=_mock_model_manager()).create_request(
        tmp_path,
        TASK,
        WORKSET_NAME,
    )

    assert request.implementation_plan.content == "Latest saved plan content"
    assert request.implementation_plan.saved_path is not None


def test_execution_service_loads_context_bundle(tmp_path):
    _make_workset(tmp_path)

    request = ExecutionService(model_manager=_mock_model_manager()).create_request(
        tmp_path,
        TASK,
        WORKSET_NAME,
        implementation_plan=_make_plan(),
    )

    assert request.context_bundle.workset_name == WORKSET_NAME
    assert request.context_bundle.files[0].path == "forge/models/manager.py"
    assert request.context_bundle.total_chars > 0


def test_execution_service_does_not_call_provider(tmp_path):
    _make_workset(tmp_path)
    manager = _mock_model_manager()

    request = ExecutionService(model_manager=manager).create_request(
        tmp_path,
        TASK,
        WORKSET_NAME,
        implementation_plan=_make_plan(),
    )

    assert request.selected_model == "qwen2.5"
    manager.config.assert_called()
    manager.ask.assert_not_called()


def test_execution_pipeline_runs_read_only_stages_in_order(tmp_path):
    _make_workset(tmp_path)
    plan = _make_plan()
    request = ExecutionRequest(
        root=tmp_path,
        task=TASK,
        workset=WORKSET_NAME,
        implementation_plan=plan,
    )

    result = ExecutionPipeline().run(request)

    assert result.status == ExecutionStatus.completed
    assert [stage.name for stage in result.stages] == [
        ExecutionStage.load_workset.value,
        ExecutionStage.load_context.value,
        ExecutionStage.load_engineering_memory.value,
        ExecutionStage.load_implementation_plan.value,
        ExecutionStage.assemble_execution_context.value,
        ExecutionStage.execution_complete.value,
    ]
    assert all(stage.status == ExecutionStatus.completed for stage in result.stages)


def test_execution_pipeline_propagates_context_between_stages(tmp_path):
    _make_workset(tmp_path)
    request = ExecutionRequest(
        root=tmp_path,
        task=TASK,
        workset=WORKSET_NAME,
        implementation_plan=_make_plan(),
    )

    class AddMetadataStage:
        name = "add_metadata"

        def run(self, context: ExecutionContext) -> ExecutionContext:
            context.metadata["handoff"] = "ready"
            return context

    class ReadMetadataStage:
        name = "read_metadata"

        def run(self, context: ExecutionContext) -> ExecutionContext:
            context.metadata["observed_handoff"] = context.metadata["handoff"]
            return context

    result = ExecutionPipeline(stages=[AddMetadataStage(), ReadMetadataStage()]).run(request)

    assert result.context is not None
    assert result.context.metadata["observed_handoff"] == "ready"
    assert [stage.name for stage in result.stages] == ["add_metadata", "read_metadata"]


def test_execution_pipeline_result_contains_loaded_context_plan_and_memory(tmp_path):
    _make_workset(tmp_path)
    MemoryManager.from_root(tmp_path).add(
        type=MemoryType.decision,
        title="Timeout validation decision",
        repository=str(tmp_path),
        workset=WORKSET_NAME,
        tags=["timeout"],
        summary="Previous work chose explicit timeout validation.",
    )
    request = ExecutionRequest(
        root=tmp_path,
        task=TASK,
        workset=WORKSET_NAME,
        implementation_plan=_make_plan(),
    )

    result = ExecutionPipeline().run(request)

    assert result.context is not None
    assert result.context.workset_data is not None
    assert result.context.context_bundle is not None
    assert result.context.context_bundle.workset_name == WORKSET_NAME
    assert result.context.implementation_plan is not None
    assert result.context.related_memory
    assert request.context_bundle is result.context.context_bundle
    assert request.implementation_plan is result.context.implementation_plan


def test_execution_pipeline_records_stage_timing(tmp_path):
    _make_workset(tmp_path)
    request = ExecutionRequest(
        root=tmp_path,
        task=TASK,
        workset=WORKSET_NAME,
        implementation_plan=_make_plan(),
    )

    result = ExecutionPipeline().run(request)

    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.completed_at >= result.started_at
    assert result.duration >= 0
    assert all(stage.completed_at >= stage.started_at for stage in result.stages)
    assert all(stage.duration >= 0 for stage in result.stages)


def test_execution_pipeline_reports_failure_status(tmp_path):
    request = ExecutionRequest(root=tmp_path, task=TASK, workset="missing")

    result = ExecutionPipeline().run(request)

    assert result.status == ExecutionStatus.failed
    assert result.stages[0].name == ExecutionStage.load_workset.value
    assert result.stages[0].status == ExecutionStatus.failed
    assert result.errors
