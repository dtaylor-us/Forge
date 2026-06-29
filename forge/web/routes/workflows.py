"""Workflow routes — Engineering Workflow Workbench (Phase 6.1)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from forge.services import workflow_service
from forge.web.deps import repo_root, template_context, templates
from forge.web.schemas import error_response

router = APIRouter()


@router.get("/workflows", response_class=HTMLResponse)
def workflows_page(request: Request) -> HTMLResponse:
    root = repo_root(request)
    runs = workflow_service.list_runs(root)
    template_defs = workflow_service.list_templates()
    context = template_context(
        request,
        active="workflows",
        runs=runs,
        template_defs=template_defs,
    )
    return templates(request).TemplateResponse(request, "workflows.html", context)


@router.get("/workflows/{run_id}", response_class=HTMLResponse)
def workflow_detail_page(request: Request, run_id: str) -> HTMLResponse:
    root = repo_root(request)
    run = workflow_service.show_run(root, run_id)
    if run is None:
        context = template_context(
            request, active="workflows", error=f"Workflow run '{run_id}' not found"
        )
        return templates(request).TemplateResponse(request, "error.html", context, status_code=404)
    template_defs = workflow_service.list_templates()
    context = template_context(
        request,
        active="workflows",
        run=run,
        template_defs=template_defs,
    )
    return templates(request).TemplateResponse(request, "workflow_detail.html", context)


@router.get("/api/workflows")
def workflows_api(request: Request, template: str | None = None) -> JSONResponse:
    root = repo_root(request)
    runs = workflow_service.list_runs(root, template=template)
    return JSONResponse({"ok": True, "data": {"runs": runs, "count": len(runs)}})


@router.get("/api/workflows/templates")
def workflow_templates_api(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "data": {"templates": workflow_service.list_templates()}})


@router.get("/api/workflows/{run_id}")
def workflow_detail_api(request: Request, run_id: str) -> JSONResponse:
    root = repo_root(request)
    run = workflow_service.show_run(root, run_id)
    if run is None:
        return error_response(f"Workflow run '{run_id}' not found", status_code=404)
    return JSONResponse({"ok": True, "data": {"run": run}})


@router.post("/api/workflows")
async def workflow_start_api(request: Request) -> JSONResponse:
    root = repo_root(request)
    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid JSON body", status_code=400)
    template = body.get("template")
    task = body.get("task", "").strip()
    if not template:
        return error_response("'template' is required", status_code=400)
    if not task:
        return error_response("'task' is required", status_code=400)
    try:
        run = workflow_service.run_workflow(root, template, task)
    except workflow_service.WorkflowServiceError as exc:
        return error_response(str(exc), status_code=422)
    return JSONResponse({"ok": True, "data": {"run": run}}, status_code=201)
