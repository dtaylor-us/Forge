"""Workset and context bundle routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse

from forge.artifacts.registry import ArtifactRegistry
from forge.services import workset_service
from forge.web.deps import repo_root, template_context, templates
from forge.web.schemas import error_response, success

router = APIRouter()
JSON_BODY = Body(default_factory=dict)


@router.get("/worksets", response_class=HTMLResponse)
def worksets_page(request: Request) -> HTMLResponse:
    root = repo_root(request)
    registry = ArtifactRegistry.from_root(root)
    context = template_context(
        request,
        active="worksets",
        worksets=[
            _with_artifact_counts(item, registry)
            for item in workset_service.list_all(root)
        ],
    )
    return templates(request).TemplateResponse(request, "worksets.html", context)


@router.get("/worksets/{name}", response_class=HTMLResponse)
def workset_detail_page(request: Request, name: str) -> HTMLResponse:
    try:
        detail = workset_service.detail(repo_root(request), name)
    except Exception as exc:
        return templates(request).TemplateResponse(
            request,
            "error.html",
            template_context(request, active="worksets", message=str(exc)),
            status_code=404,
        )
    registry = ArtifactRegistry.from_root(repo_root(request))
    context = template_context(
        request,
        active="worksets",
        workset=detail,
        related_artifacts=_related_artifacts(detail.get("name", name), registry),
    )
    return templates(request).TemplateResponse(request, "workset_detail.html", context)


@router.get("/api/worksets")
def worksets_api(request: Request):
    return success({"worksets": workset_service.list_all(repo_root(request))})


@router.get("/api/worksets/{name}")
def workset_detail_api(request: Request, name: str):
    try:
        return success(workset_service.detail(repo_root(request), name))
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=404)


@router.post("/api/worksets/suggest")
def workset_suggest_api(
    request: Request,
    payload: dict[str, object] = JSON_BODY,
):
    query = str(payload.get("query", ""))
    max_results = int(payload.get("max_results", 20))
    include_tests = bool(payload.get("include_tests", False))
    return success(
        workset_service.suggest(
            repo_root(request),
            query,
            max_results=max_results,
            include_tests=include_tests,
        )
    )


@router.post("/api/worksets/create")
def workset_create_api(
    request: Request,
    payload: dict[str, object] = JSON_BODY,
):
    try:
        return success(
            workset_service.create(
                repo_root(request),
                str(payload.get("name", "")),
                str(payload.get("query", "")),
                max_results=int(payload.get("max_results", 20)),
                include_tests=bool(payload.get("include_tests", False)),
                force=bool(payload.get("force", False)),
            )
        )
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=400)


def _with_artifact_counts(
    workset: dict[str, object],
    registry: ArtifactRegistry,
) -> dict[str, object]:
    enriched = dict(workset)
    related = _related_artifacts(str(workset.get("name") or ""), registry)
    enriched["related_plans"] = sum(
        1 for artifact in related if artifact.get("artifact_type") == "implementation_plan"
    )
    enriched["related_patches"] = sum(
        1 for artifact in related if artifact.get("artifact_type") == "patch"
    )
    enriched["related_artifacts"] = len(related)
    return enriched


def _related_artifacts(
    workset_name: str,
    registry: ArtifactRegistry,
) -> list[dict[str, object]]:
    return [
        artifact.to_dict()
        for artifact in registry.enumerate()
        if artifact.workset_name == workset_name
    ]


@router.post("/api/worksets/{name}/refresh")
def workset_refresh_api(request: Request, name: str):
    try:
        return success(workset_service.refresh(repo_root(request), name))
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=404)


@router.delete("/api/worksets/{name}")
def workset_delete_api(request: Request, name: str):
    try:
        return success(workset_service.delete(repo_root(request), name))
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=404)


@router.post("/api/worksets/{name}/context")
def workset_context_api(
    request: Request,
    name: str,
    payload: dict[str, object] = JSON_BODY,
):
    try:
        return success(
            workset_service.generate_context(
                repo_root(request),
                name,
                max_lines_per_file=int(payload.get("max_lines_per_file", 120)),
                include_full=bool(payload.get("include_full", False)),
            )
        )
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=400)
