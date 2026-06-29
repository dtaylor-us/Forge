"""Read-oriented registry for Forge engineering artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from forge.artifacts.discovery import discover_artifacts
from forge.artifacts.models import Artifact, ArtifactRelationship, ArtifactType


class ArtifactRegistry:
    """Unified read-only view over project-local engineering artifacts."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._artifacts: list[Artifact] | None = None

    @classmethod
    def from_root(cls, root: Path | str) -> ArtifactRegistry:
        """Create a registry for a project root."""
        return cls(root)

    def discover(self) -> list[Artifact]:
        """Discover and cache artifacts for this registry."""
        self._artifacts = discover_artifacts(self.root)
        return list(self._artifacts)

    def enumerate(self) -> list[Artifact]:
        """Return all discovered artifacts."""
        return list(self._ensure_artifacts())

    def by_type(self, artifact_type: ArtifactType | str) -> list[Artifact]:
        """Return artifacts of a given type."""
        resolved_type = ArtifactType(artifact_type)
        return [
            artifact
            for artifact in self._ensure_artifacts()
            if artifact.artifact_type == resolved_type
        ]

    def by_id(self, artifact_id: str) -> Artifact | None:
        """Return an artifact by registry identifier."""
        return next(
            (artifact for artifact in self._ensure_artifacts() if artifact.id == artifact_id),
            None,
        )

    def relationships(self, artifact_id: str | None = None) -> list[ArtifactRelationship]:
        """Return known sparse relationships."""
        relationships = [
            relationship
            for artifact in self._ensure_artifacts()
            for relationship in artifact.relationships
        ]
        if artifact_id is None:
            return relationships
        return [
            relationship
            for relationship in relationships
            if relationship.source_id == artifact_id or relationship.target_id == artifact_id
        ]

    def related(self, artifact_id: str) -> list[Artifact]:
        """Return artifacts directly connected by known relationships."""
        related_ids = {
            relationship.target_id
            for relationship in self.relationships()
            if relationship.source_id == artifact_id
        }
        related_ids.update(
            relationship.source_id
            for relationship in self.relationships()
            if relationship.target_id == artifact_id
        )
        return [artifact for artifact in self._ensure_artifacts() if artifact.id in related_ids]

    def _ensure_artifacts(self) -> Iterable[Artifact]:
        if self._artifacts is None:
            self.discover()
        return self._artifacts or []
