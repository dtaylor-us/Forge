"""Discovery of existing Forge engineering artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from forge.artifacts.metadata import (
    artifact_id,
    file_created_at,
    file_updated_at,
    first_markdown_heading,
    read_json,
    relative_to_root,
)
from forge.artifacts.models import Artifact, ArtifactRelationship, ArtifactType
from forge.project.paths import ForgePaths


def discover_artifacts(root: Path) -> list[Artifact]:
    """Build a read-only unified view of artifacts under a project root."""
    paths = ForgePaths.from_root(root)
    discovered: list[Artifact] = []
    repository = _repository_artifact(paths)
    if repository is not None:
        discovered.append(repository)
    discovered.extend(_workset_artifacts(paths))
    discovered.extend(_context_bundle_artifacts(paths))
    discovered.extend(_implementation_plan_artifacts(paths))
    discovered.extend(_memory_entry_artifacts(paths))
    discovered.extend(_patch_artifacts(paths))
    return sorted(discovered, key=lambda artifact: (artifact.artifact_type.value, artifact.name))


def _repository_artifact(paths: ForgePaths) -> Artifact | None:
    metadata_path = paths.project_forge_dir / "project.json"
    if not metadata_path.exists():
        return None

    data = read_json(metadata_path)
    relative_path = relative_to_root(metadata_path, paths.repo_root)
    name = data.get("project_name") or paths.repo_root.name
    intrinsic_id = data.get("project_name") or None
    return Artifact(
        id=artifact_id(ArtifactType.repository, relative_path, intrinsic_id),
        artifact_type=ArtifactType.repository,
        name=name,
        description="Forge repository metadata",
        created_at=data.get("created_at") or file_created_at(metadata_path),
        updated_at=data.get("updated_at") or file_updated_at(metadata_path),
        project_root=paths.repo_root,
        relative_path=relative_path,
        producing_service="ProjectService",
        producing_command="forge init",
        metadata=data or {},
    )


def _workset_artifacts(paths: ForgePaths) -> Iterable[Artifact]:
    for path in _json_files(paths.worksets_dir):
        data = read_json(path)
        name = str(data.get("name") or path.stem)
        relative_path = relative_to_root(path, paths.repo_root)
        yield Artifact(
            id=artifact_id(ArtifactType.workset, relative_path, name),
            artifact_type=ArtifactType.workset,
            name=name,
            description=str(data.get("query") or ""),
            created_at=data.get("created_at") or file_created_at(path),
            updated_at=data.get("updated_at") or file_updated_at(path),
            project_root=paths.repo_root,
            relative_path=relative_path,
            producing_service="WorksetService",
            producing_command="forge workset",
            workset_name=name,
            metadata={
                "schema_version": data.get("schema_version"),
                "query": data.get("query"),
                "file_count": _artifact_file_count(data),
                "include_tests": data.get("include_tests"),
                "max_results": data.get("max_results"),
            },
        )


def _context_bundle_artifacts(paths: ForgePaths) -> Iterable[Artifact]:
    for path in _files(paths.context_dir, ("*.md", "*.json")):
        relative_path = relative_to_root(path, paths.repo_root)
        name = path.stem
        workset_name = _workset_from_artifact_stem(name, suffixes=("context", "bundle", "planning"))
        yield Artifact(
            id=artifact_id(ArtifactType.context_bundle, relative_path),
            artifact_type=ArtifactType.context_bundle,
            name=name,
            description=first_markdown_heading(path),
            created_at=file_created_at(path),
            updated_at=file_updated_at(path),
            project_root=paths.repo_root,
            relative_path=relative_path,
            producing_service="PlanningService",
            producing_command="forge plan",
            workset_name=workset_name,
            metadata={"size_bytes": _size(path), "suffix": path.suffix},
            relationships=_workset_relationship(
                artifact_id(ArtifactType.context_bundle, relative_path), workset_name
            ),
        )


def _implementation_plan_artifacts(paths: ForgePaths) -> Iterable[Artifact]:
    for path in _files(paths.plans_dir, ("*.md",)):
        relative_path = relative_to_root(path, paths.repo_root)
        name = path.stem
        workset_name = _workset_from_artifact_stem(name)
        yield Artifact(
            id=artifact_id(ArtifactType.implementation_plan, relative_path),
            artifact_type=ArtifactType.implementation_plan,
            name=name,
            description=first_markdown_heading(path),
            created_at=file_created_at(path),
            updated_at=file_updated_at(path),
            project_root=paths.repo_root,
            relative_path=relative_path,
            producing_service="PlanningService",
            producing_command="forge plan --save",
            workset_name=workset_name,
            metadata={"size_bytes": _size(path), "suffix": path.suffix},
            relationships=_workset_relationship(
                artifact_id(ArtifactType.implementation_plan, relative_path), workset_name
            ),
        )


def _memory_entry_artifacts(paths: ForgePaths) -> Iterable[Artifact]:
    index = paths.memory_dir / "index.json"
    for path in _json_files(paths.memory_dir, recursive=True):
        if path == index:
            continue
        data = read_json(path)
        intrinsic_id = data.get("id")
        relative_path = relative_to_root(path, paths.repo_root)
        memory_type = data.get("type")
        artifact_type = ArtifactType.adr if memory_type == "adr" else ArtifactType.memory_entry
        name = str(data.get("title") or intrinsic_id or path.stem)
        relationships = []
        source_id = artifact_id(artifact_type, relative_path, intrinsic_id)
        for workset_name in _as_strings(data.get("related_worksets")):
            relationships.extend(_workset_relationship(source_id, workset_name))
        related_worksets = _as_strings(data.get("related_worksets"))
        if data.get("workset") and data.get("workset") not in related_worksets:
            relationships.extend(_workset_relationship(source_id, str(data["workset"])))
        for plan_id in _as_strings(data.get("related_plans")):
            relationships.append(
                ArtifactRelationship(
                    source_id=source_id,
                    target_id=artifact_id(ArtifactType.memory_entry, "", plan_id),
                    relationship_type="related_plan",
                )
            )
        yield Artifact(
            id=source_id,
            artifact_type=artifact_type,
            name=name,
            description=str(data.get("summary") or ""),
            created_at=data.get("created_at") or file_created_at(path),
            updated_at=file_updated_at(path),
            project_root=paths.repo_root,
            relative_path=relative_path,
            producing_service="MemoryManager",
            producing_command="forge memory",
            workset_name=data.get("workset") or None,
            metadata={
                "memory_type": memory_type,
                "tags": data.get("tags", []),
                "related_files": data.get("related_files", []),
                "source_path": data.get("source_path", ""),
            },
            relationships=tuple(relationships),
        )


def _patch_artifacts(paths: ForgePaths) -> Iterable[Artifact]:
    for path in _files(paths.patches_dir, ("*.patch",)):
        relative_path = relative_to_root(path, paths.repo_root)
        name = path.name
        yield Artifact(
            id=artifact_id(ArtifactType.patch, relative_path, name),
            artifact_type=ArtifactType.patch,
            name=name,
            created_at=file_created_at(path),
            updated_at=file_updated_at(path),
            project_root=paths.repo_root,
            relative_path=relative_path,
            producing_service="PatchService",
            producing_command="forge implement",
            metadata={"size_bytes": _size(path), "suffix": path.suffix},
        )


def _files(directory: Path, patterns: tuple[str, ...]) -> list[Path]:
    if not directory.exists():
        return []
    result: list[Path] = []
    for pattern in patterns:
        result.extend(path for path in directory.glob(pattern) if path.is_file())
    return sorted(set(result), key=lambda path: path.as_posix())


def _json_files(directory: Path, *, recursive: bool = False) -> list[Path]:
    if not directory.exists():
        return []
    pattern = "**/*.json" if recursive else "*.json"
    return sorted(
        (path for path in directory.glob(pattern) if path.is_file()),
        key=lambda p: p.as_posix(),
    )


def _workset_from_artifact_stem(stem: str, suffixes: tuple[str, ...] = ()) -> str | None:
    for suffix in suffixes:
        marker = f"-{suffix}-"
        if marker in stem:
            return stem.split(marker, maxsplit=1)[0]
    if "-" not in stem:
        return None
    candidate = stem.rsplit("-", maxsplit=1)[0]
    return candidate or None


def _workset_relationship(
    source_id: str,
    workset_name: str | None,
) -> tuple[ArtifactRelationship, ...]:
    if not workset_name:
        return ()
    return (
        ArtifactRelationship(
            source_id=source_id,
            target_id=artifact_id(ArtifactType.workset, "", workset_name),
            relationship_type="derived_from_workset",
        ),
    )


def _as_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _artifact_file_count(data: dict[str, Any]) -> int:
    files = data.get("files", [])
    return len(files) if isinstance(files, list) else 0


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
