"""Read-only Engineering Execution routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from forge.artifacts.registry import ArtifactRegistry
from forge.execution.execution_service import ExecutionService, ExecutionServiceError
from forge.execution.models import ExecutionStage
from forge.models.manager import ModelManager
from forge.web.deps import repo_root, template_context, templates
from forge.web.schemas import error_response, success

router = APIRouter()


@router.get("/execution", response_class=HTMLResponse)
def execution_page(request: Request) -> HTMLResponse:
    root = repo_root(request)
    prepared = _prepare_latest_execution(root)
    context = template_context(
        request,
        active="execution",
        pipeline=_pipeline(),
        prepared=prepared,
    )
    return templates(request).TemplateResponse(request, "execution.html", context)


@router.get("/api/execution/prepared")
def execution_prepared_api(request: Request) -> dict[str, object]:
    prepared = _prepare_latest_execution(repo_root(request))
    if prepared.get("error"):
        return error_response(
            str(prepared["error"]),
            type_name="ExecutionServiceError",
            status_code=404,
        )
    return success(prepared)


def _prepare_latest_execution(root) -> dict[str, object]:
    plan = _latest_plan_artifact(root)
    if plan is None or not plan.get("workset_name"):
        return {
            "status": "not_ready",
            "error": "Save an implementation plan for a workset to prepare an ExecutionRequest.",
        }

    task = str(plan.get("description") or plan.get("name") or "Prepared execution")
    workset = str(plan["workset_name"])
    selected_model = _default_model()
    try:
        request = ExecutionService().create_request(
            root,
            task,
            workset,
            model=selected_model,
        )
    except ExecutionServiceError as exc:
        return {"status": "blocked", "error": str(exc), "plan": plan}

    bundle = request.context_bundle
    implementation_plan = request.implementation_plan
    return {
        "status": request.status.value,
        "task": request.task,
        "workset": request.workset,
        "selected_model": request.selected_model,
        "created_at": request.created_at.isoformat(),
        "target": {
            "root": request.target.root if request.target else str(root),
            "workset_name": request.target.workset_name if request.target else request.workset,
        },
        "context_summary": {
            "file_count": len(bundle.files) if bundle else 0,
            "total_tokens": bundle.total_tokens if bundle else 0,
            "total_chars": bundle.total_chars if bundle else 0,
        },
        "memory_summary": {
            "count": len(request.related_memory),
            "items": [
                {
                    "id": result.item.id,
                    "title": result.item.title,
                    "type": result.item.type.value,
                    "score": result.score,
                }
                for result in request.related_memory
            ],
        },
        "plan_summary": {
            "workset": implementation_plan.workset_name if implementation_plan else workset,
            "model": implementation_plan.model if implementation_plan else selected_model,
            "generated_at": (
                implementation_plan.generated_at.isoformat() if implementation_plan else None
            ),
            "saved_path": (
                str(implementation_plan.saved_path)
                if implementation_plan and implementation_plan.saved_path
                else None
            ),
        },
        "prompt_summary": {
            "chars": len(request.prompt),
            "preview": request.prompt[:900],
        },
        "metadata": request.metadata,
        "plan": plan,
    }


def _latest_plan_artifact(root) -> dict[str, object] | None:
    plans = [
        artifact.to_dict()
        for artifact in ArtifactRegistry.from_root(root).by_type("implementation_plan")
    ]
    plans.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return plans[0] if plans else None


def _pipeline() -> list[dict[str, str]]:
    labels = {
        ExecutionStage.load_workset: "Load Workset",
        ExecutionStage.load_context: "Load Context",
        ExecutionStage.load_engineering_memory: "Load Engineering Memory",
        ExecutionStage.load_implementation_plan: "Load Implementation Plan",
        ExecutionStage.assemble_execution_context: "Assemble Execution Context",
        ExecutionStage.execution_complete: "Execution Ready",
    }
    return [
        {"name": stage.value, "label": labels[stage], "status": "available"}
        for stage in ExecutionStage
    ]


def _default_model() -> str | None:
    try:
        return ModelManager().default_model()
    except Exception:
        return None
