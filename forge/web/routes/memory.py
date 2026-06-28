"""Engineering memory routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse

from forge.memory.models import MemoryType
from forge.services import memory_service
from forge.web.deps import repo_root, template_context, templates
from forge.web.schemas import error_response, success

router = APIRouter()
JSON_BODY = Body(default_factory=dict)


@router.get("/memory", response_class=HTMLResponse)
def memory_page(request: Request) -> HTMLResponse:
    context = template_context(
        request,
        active="memory",
        items=memory_service.list_timeline(repo_root(request)),
    )
    return templates(request).TemplateResponse(request, "memory.html", context)


@router.get("/memory/{item_id}", response_class=HTMLResponse)
def memory_detail_page(request: Request, item_id: str) -> HTMLResponse:
    try:
        item = memory_service.get(repo_root(request), item_id)
    except Exception as exc:
        return templates(request).TemplateResponse(
            request,
            "error.html",
            template_context(request, active="memory", message=str(exc)),
            status_code=404,
        )
    return templates(request).TemplateResponse(
        request,
        "memory_detail.html",
        template_context(request, active="memory", item=item),
    )


@router.get("/api/memory/search")
def memory_search_api(request: Request, q: str = "", max_results: int = 10):
    return success(memory_service.search(repo_root(request), q, max_results=max_results))


@router.get("/api/memory/timeline")
def memory_timeline_api(request: Request):
    return success({"items": memory_service.list_timeline(repo_root(request))})


@router.post("/api/memory/add")
def memory_add_api(
    request: Request,
    payload: dict[str, object] = JSON_BODY,
):
    try:
        type_name = str(payload.get("type", "followup"))
        tags = payload.get("tags", [])
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        return success(
            memory_service.add_item(
                repo_root(request),
                type=MemoryType(type_name),
                title=str(payload.get("title", "")),
                summary=str(payload.get("summary", "")),
                workset=str(payload.get("workset", "")),
                tags=list(tags) if isinstance(tags, list) else [],
            )
        )
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=400)


@router.post("/api/decisions/create")
def decision_create_api(
    request: Request,
    payload: dict[str, object] = JSON_BODY,
):
    try:
        return success(
            memory_service.create_decision(
                repo_root(request),
                str(payload.get("title", "")),
                str(payload.get("summary", "")),
                str(payload.get("workset", "")),
            )
        )
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=400)


@router.post("/api/investigations/create")
def investigation_create_api(
    request: Request,
    payload: dict[str, object] = JSON_BODY,
):
    try:
        return success(
            memory_service.create_investigation(
                repo_root(request),
                str(payload.get("title", "")),
                str(payload.get("summary", "")),
                str(payload.get("workset", "")),
            )
        )
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=400)
