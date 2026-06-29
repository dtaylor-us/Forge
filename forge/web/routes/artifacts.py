"""Engineering artifact explorer routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from forge.artifacts.registry import ArtifactRegistry
from forge.web.deps import repo_root, template_context, templates
from forge.web.schemas import success

router = APIRouter()


@router.get("/artifacts", response_class=HTMLResponse)
def artifacts_page(request: Request) -> HTMLResponse:
    root = repo_root(request)
    registry = ArtifactRegistry.from_root(root)
    artifacts = [artifact.to_dict() for artifact in registry.enumerate()]
    relationships = [
        {
            "source_id": relationship.source_id,
            "target_id": relationship.target_id,
            "relationship_type": relationship.relationship_type,
            "metadata": relationship.metadata,
        }
        for relationship in registry.relationships()
    ]
    context = template_context(
        request,
        active="artifacts",
        artifacts=artifacts,
        relationships=relationships,
        type_counts=_type_counts(artifacts),
    )
    return templates(request).TemplateResponse(request, "artifacts.html", context)


@router.get("/api/artifacts")
def artifacts_api(request: Request) -> dict[str, object]:
    registry = ArtifactRegistry.from_root(repo_root(request))
    return success(
        {
            "artifacts": [artifact.to_dict() for artifact in registry.enumerate()],
            "relationships": [
                {
                    "source_id": relationship.source_id,
                    "target_id": relationship.target_id,
                    "relationship_type": relationship.relationship_type,
                    "metadata": relationship.metadata,
                }
                for relationship in registry.relationships()
            ],
        }
    )


def _type_counts(artifacts: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for artifact in artifacts:
        artifact_type = str(artifact.get("artifact_type") or "unknown")
        counts[artifact_type] = counts.get(artifact_type, 0) + 1
    return counts
