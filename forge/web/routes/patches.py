"""Patch explorer routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from forge.services import patch_service
from forge.web.deps import repo_root, template_context, templates
from forge.web.schemas import error_response, success

router = APIRouter()


@router.get("/patches", response_class=HTMLResponse)
def patches_page(request: Request) -> HTMLResponse:
    root = repo_root(request)
    patches = [_enrich_patch(patch) for patch in patch_service.list_all(root)]
    selected = patch_service.show(root, patches[0]["name"]) if patches else None
    context = template_context(
        request,
        active="patches",
        patches=patches,
        selected=_enrich_patch(selected) if selected else None,
    )
    return templates(request).TemplateResponse(request, "patches.html", context)


@router.get("/api/patches")
def patches_api(request: Request) -> dict[str, object]:
    patches = [_enrich_patch(patch) for patch in patch_service.list_all(repo_root(request))]
    return success({"patches": patches})


@router.get("/api/patches/{name}")
def patch_show_api(request: Request, name: str) -> dict[str, object]:
    try:
        return success(_enrich_patch(patch_service.show(repo_root(request), name)))
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=404)


@router.post("/api/patches/{name}/validate")
def patch_validate_api(request: Request, name: str) -> dict[str, object]:
    try:
        return success(_enrich_patch(patch_service.validate(repo_root(request), name)))
    except Exception as exc:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=404)


def _enrich_patch(patch: dict[str, object] | None) -> dict[str, object]:
    if patch is None:
        return {}
    content = str(patch.get("content") or "")
    added = 0
    removed = 0
    for line in content.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    enriched = dict(patch)
    enriched["lines_added"] = added
    enriched["lines_removed"] = removed
    enriched["status"] = "valid" if patch.get("valid") else "needs_review"
    enriched["source_model"] = "forge implement"
    return enriched
