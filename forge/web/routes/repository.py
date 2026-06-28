"""Repository routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from forge.services import repository_service
from forge.web.deps import repo_root, template_context, templates
from forge.web.schemas import success

router = APIRouter()


@router.get("/repository", response_class=HTMLResponse)
def repository_page(request: Request) -> HTMLResponse:
    root = repo_root(request)
    context = template_context(
        request,
        active="repository",
        detection=repository_service.detect(root),
        tree=repository_service.tree(root, max_depth=3)["lines"],
    )
    return templates(request).TemplateResponse(request, "repository.html", context)


@router.get("/api/repository/detect")
def repository_detect_api(request: Request) -> dict[str, object]:
    return success(repository_service.detect(repo_root(request)))


@router.get("/api/repository/tree")
def repository_tree_api(request: Request, max_depth: int = Query(default=3, ge=0, le=10)):
    return success(repository_service.tree(repo_root(request), max_depth=max_depth))


@router.get("/api/repository/search")
def repository_search_api(
    request: Request,
    q: str = "",
    max_results: int = Query(default=100, ge=1, le=500),
):
    return success(repository_service.search(repo_root(request), q, max_results=max_results))
