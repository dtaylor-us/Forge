"""Common models for Forge engineering artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ArtifactType(StrEnum):
    """Known engineering artifact types.

    The enum includes planned future types so registry consumers can use one
    vocabulary while storage remains owned by existing subsystems.
    """

    repository = "repository"
    workset = "workset"
    context_bundle = "context_bundle"
    implementation_plan = "implementation_plan"
    memory_entry = "memory_entry"
    patch = "patch"
    execution = "execution"
    verification = "verification"
    repair = "repair"
    review = "review"
    documentation = "documentation"
    adr = "adr"
    workflow = "workflow"
    policy_evaluation = "policy_evaluation"
    patch_application = "patch_application"


@dataclass(frozen=True)
class ArtifactRelationship:
    """Sparse relationship from one artifact to another."""

    source_id: str
    target_id: str
    relationship_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Artifact:
    """Read-only registry representation of an engineering artifact."""

    id: str
    artifact_type: ArtifactType
    name: str
    description: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    project_root: Path | None = None
    relative_path: str | None = None
    producing_service: str | None = None
    producing_command: str | None = None
    workset_name: str | None = None
    related_plan: str | None = None
    related_patch: str | None = None
    related_execution: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    relationships: tuple[ArtifactRelationship, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "id": self.id,
            "artifact_type": self.artifact_type.value,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_root": str(self.project_root) if self.project_root else None,
            "relative_path": self.relative_path,
            "producing_service": self.producing_service,
            "producing_command": self.producing_command,
            "workset_name": self.workset_name,
            "related_plan": self.related_plan,
            "related_patch": self.related_patch,
            "related_execution": self.related_execution,
            "metadata": self.metadata,
            "relationships": [
                {
                    "source_id": relationship.source_id,
                    "target_id": relationship.target_id,
                    "relationship_type": relationship.relationship_type,
                    "metadata": relationship.metadata,
                }
                for relationship in self.relationships
            ],
        }
