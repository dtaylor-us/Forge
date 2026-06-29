"""Planning routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse

from forge.artifacts.registry import ArtifactRegistry
from forge.services import planning_service, workset_service
from forge.web.deps import repo_root, template_context, templates
from forge.web.schemas import error_response, success

router = APIRouter()
JSON_BODY = Body(default_factory=dict)


@router.get("/planning", response_class=HTMLResponse)
def planning_page(request: Request) -> HTMLResponse:
    root = repo_root(request)
    registry = ArtifactRegistry.from_root(root)
    plan_artifacts = [
        artifact.to_dict() for artifact in registry.by_type("implementation_plan")
    ]
    context = template_context(
        request,
        active="planning",
        worksets=workset_service.list_all(root),
        plan_artifacts=plan_artifacts,
    )
    return templates(request).TemplateResponse(request, "planning.html", context)


@router.post("/api/plans/generate")
def plan_generate_api(
    request: Request,
    payload: dict[str, object] = JSON_BODY,
):
    try:
        return success(
            planning_service.generate(
                repo_root(request),
                str(payload.get("task", "")),
                str(payload.get("workset", "")),
                model=str(payload["model"]) if payload.get("model") else None,
                save=bool(payload.get("save", False)),
                use_memory=bool(payload.get("use_memory", True)),
                timeout_seconds=(
                    int(payload["timeout"]) if payload.get("timeout") not in (None, "") else None
                ),
            )
        )
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=400)
