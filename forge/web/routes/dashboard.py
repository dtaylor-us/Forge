"""Dashboard routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from forge.project.paths import ForgePaths
from forge.services import memory_service, project_service, workset_service
from forge.web.deps import repo_root, template_context, templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    root = repo_root(request)
    paths = ForgePaths.from_root(root)
    plans = []
    if paths.plans_dir.exists():
        plans = sorted(paths.plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    context = template_context(
        request,
        active="dashboard",
        project=project_service.project_info(root),
        worksets=workset_service.list_all(root)[:5],
        plans=[{"name": p.name, "path": str(p)} for p in plans[:5]],
        memory_items=memory_service.list_timeline(root)[:5],
    )
    return templates(request).TemplateResponse(request, "dashboard.html", context)
