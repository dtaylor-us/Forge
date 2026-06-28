"""Project routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from forge.services import project_service
from forge.web.deps import repo_root, template_context, templates
from forge.web.schemas import error_response, success

router = APIRouter()


@router.get("/project", response_class=HTMLResponse)
def project_page(request: Request) -> HTMLResponse:
    context = template_context(
        request,
        active="project",
        project=project_service.project_info(repo_root(request)),
    )
    return templates(request).TemplateResponse(request, "project.html", context)


@router.get("/api/project")
def project_api(request: Request) -> dict[str, object]:
    return success(project_service.project_info(repo_root(request)))


@router.post("/api/project/init")
def project_init_api(request: Request, force: bool = False):
    try:
        return success(project_service.initialize(repo_root(request), force=force))
    except FileExistsError as exc:
        return error_response(str(exc), type_name="FileExistsError", status_code=409)
