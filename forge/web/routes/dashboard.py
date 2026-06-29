"""Dashboard routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from forge.artifacts.registry import ArtifactRegistry
from forge.config.manager import ConfigManager
from forge.services import (
    git_service,
    memory_service,
    project_service,
    repository_service,
    workflow_service,
    workset_service,
)
from forge.web.deps import repo_root, template_context, templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    root = repo_root(request)
    registry = ArtifactRegistry.from_root(root)
    artifacts = [artifact.to_dict() for artifact in registry.enumerate()]
    project = project_service.project_info(root)
    detection = repository_service.detect(root)
    git_result = git_service.branch(root)
    branch = git_result.get("branch") or "—"
    worksets = workset_service.list_all(root)
    plans = project_service.recent_plans(root, limit=5)
    memory_items = memory_service.list_timeline(root)[:5]
    workflow_runs = workflow_service.list_runs(root)
    latest_run = workflow_runs[0] if workflow_runs else None
    context = template_context(
        request,
        active="dashboard",
        project=project,
        detection=detection,
        branch=branch,
        worksets=worksets[:5],
        plans=plans,
        memory_items=memory_items,
        metrics=_metrics(artifacts, worksets, plans, memory_items, workflow_runs),
        workflow=_workflow(),
        activity=_activity(artifacts, memory_items, workflow_runs),
        model_config=_model_config(),
        latest_run=latest_run,
        next_action=_next_action(latest_run, artifacts),
    )
    return templates(request).TemplateResponse(request, "dashboard.html", context)


def _metrics(
    artifacts: list[dict[str, object]],
    worksets: list[dict[str, object]],
    plans: list[dict[str, object]],
    memory_items: list[dict[str, object]],
    workflow_runs: list[dict[str, object]] | None = None,
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
        "workflow_runs": len(workflow_runs) if workflow_runs else 0,
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


def _next_action(
    latest_run: dict[str, object] | None,
    artifacts: list[dict[str, object]],
) -> dict[str, str]:
    if latest_run is None:
        return {
            "label": "Start your first workflow",
            "href": "/workflows",
            "icon": "git-branch-plus",
        }
    status = str(latest_run.get("status") or "")
    patch_path = latest_run.get("patch_path")
    verification_status = latest_run.get("verification_status")
    policy_status = latest_run.get("policy_status")
    if status == "failed":
        return {
            "label": "Review failed workflow",
            "href": f"/workflows/{latest_run.get('id', '')}",
            "icon": "alert-circle",
        }
    if status == "completed":
        if policy_status == "pass" and patch_path:
            return {"label": "Apply patch", "href": "/patches", "icon": "git-pull-request-arrow"}
        if verification_status == "fail":
            return {
                "label": "Open Verification Report",
                "href": "/artifacts",
                "icon": "badge-check",
            }
        if policy_status == "fail":
            return {"label": "Open Policy Report", "href": "/artifacts", "icon": "shield-alert"}
        if patch_path:
            return {
                "label": "Review generated patch",
                "href": "/patches",
                "icon": "git-pull-request-arrow",
            }
    return {"label": "Start a new workflow", "href": "/workflows", "icon": "git-branch-plus"}


def _activity(
    artifacts: list[dict[str, object]],
    memory_items: list[dict[str, object]],
    workflow_runs: list[dict[str, object]] | None = None,
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
                "href": "",
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
                "href": "/memory",
            }
        )
    for run in (workflow_runs or []):
        run_status = str(run.get("status") or "")
        events.append(
            {
                "time": str(run.get("completed_at") or run.get("started_at") or ""),
                "artifact": str(run.get("task") or run.get("id") or "Workflow"),
                "related_workset": str(run.get("template") or "workflow").title(),
                "status": f"workflow {run_status}",
                "type": "Workflow Run",
                "href": f"/workflows/{run.get('id', '')}",
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
