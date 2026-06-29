"""Dashboard routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from forge.artifacts.registry import ArtifactRegistry
from forge.config.manager import ConfigManager
from forge.services import memory_service, project_service, repository_service, workset_service
from forge.web.deps import repo_root, template_context, templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    root = repo_root(request)
    registry = ArtifactRegistry.from_root(root)
    artifacts = [artifact.to_dict() for artifact in registry.enumerate()]
    project = project_service.project_info(root)
    detection = repository_service.detect(root)
    worksets = workset_service.list_all(root)
    plans = project_service.recent_plans(root, limit=5)
    memory_items = memory_service.list_timeline(root)[:5]
    context = template_context(
        request,
        active="dashboard",
        project=project,
        detection=detection,
        worksets=worksets[:5],
        plans=plans,
        memory_items=memory_items,
        metrics=_metrics(artifacts, worksets, plans, memory_items),
        workflow=_workflow(),
        activity=_activity(artifacts, memory_items),
        model_config=_model_config(),
    )
    return templates(request).TemplateResponse(request, "dashboard.html", context)


def _metrics(
    artifacts: list[dict[str, object]],
    worksets: list[dict[str, object]],
    plans: list[dict[str, object]],
    memory_items: list[dict[str, object]],
) -> dict[str, int]:
    artifact_counts: dict[str, int] = {}
    for artifact in artifacts:
        key = str(artifact.get("artifact_type") or "")
        artifact_counts[key] = artifact_counts.get(key, 0) + 1
    return {
        "repositories": artifact_counts.get("repository", 0),
        "worksets": len(worksets),
        "context_bundles": artifact_counts.get("context_bundle", 0),
        "plans": artifact_counts.get("implementation_plan", len(plans)),
        "memory_entries": artifact_counts.get("memory_entry", len(memory_items)),
        "patches": artifact_counts.get("patch", 0),
        "execution_requests": artifact_counts.get("execution", 0),
        "artifact_count": len(artifacts),
    }


def _workflow() -> list[dict[str, str]]:
    return [
        {"label": "Repository Intelligence", "status": "complete"},
        {"label": "Worksets", "status": "available"},
        {"label": "Context Engineering", "status": "available"},
        {"label": "Planning", "status": "available"},
        {"label": "Implementation", "status": "available"},
        {"label": "Patch Review", "status": "available"},
        {"label": "Verification", "status": "future"},
        {"label": "Patch Apply", "status": "future"},
    ]


def _activity(
    artifacts: list[dict[str, object]],
    memory_items: list[dict[str, object]],
) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for artifact in artifacts:
        artifact_type = str(artifact.get("artifact_type") or "artifact")
        events.append(
            {
                "time": str(artifact.get("created_at") or artifact.get("updated_at") or ""),
                "artifact": str(artifact.get("name") or artifact.get("id") or "Artifact"),
                "related_workset": str(artifact.get("workset_name") or "Repository"),
                "status": _status_for_artifact(artifact_type),
                "type": artifact_type.replace("_", " ").title(),
            }
        )
    for item in memory_items:
        events.append(
            {
                "time": str(item.get("created_at") or ""),
                "artifact": str(item.get("title") or "Memory updated"),
                "related_workset": str(item.get("workset") or "Engineering Memory"),
                "status": "memory updated",
                "type": str(item.get("type") or "Memory"),
            }
        )
    events.sort(key=lambda event: event["time"], reverse=True)
    return events[:8]


def _status_for_artifact(artifact_type: str) -> str:
    statuses = {
        "workset": "workset created",
        "context_bundle": "context generated",
        "implementation_plan": "plan generated",
        "patch": "patch generated",
        "memory_entry": "memory updated",
        "repository": "artifact discovered",
    }
    return statuses.get(artifact_type, "artifact discovered")


def _model_config() -> dict[str, str]:
    try:
        config = ConfigManager().load()
    except Exception:
        return {"provider": "unknown", "default_model": "unknown"}
    return {"provider": config.provider.value, "default_model": config.default_model}
