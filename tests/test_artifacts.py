"""Tests for the unified engineering artifact registry."""

from __future__ import annotations

import json
from pathlib import Path

from forge.artifacts import ArtifactRegistry, ArtifactType
from forge.memory.models import MemoryItem, MemoryType
from forge.memory.store import save_item
from forge.patches.service import save_patch_content
from forge.project.metadata import build_metadata, save_metadata
from forge.project.paths import ForgePaths
from forge.worksets.store import save as save_workset


def _write_project_metadata(root: Path) -> None:
    paths = ForgePaths.from_root(root)
    save_metadata(paths.project_forge_dir, build_metadata(root, "forge-test"))


def _write_workset(root: Path, name: str = "auth") -> None:
    save_workset(
        root,
        {
            "schema_version": 1,
            "name": name,
            "query": "authentication flow",
            "root": str(root),
            "created_at": "2026-06-28T00:00:00+00:00",
            "updated_at": "2026-06-28T00:01:00+00:00",
            "include_tests": False,
            "max_results": 10,
            "files": [{"path": "src/auth.py"}],
        },
    )


def _write_memory(root: Path) -> MemoryItem:
    item = MemoryItem(
        id="mem123",
        type=MemoryType.plan,
        title="Auth plan memory",
        created_at="2026-06-28T00:02:00+00:00",
        repository=str(root),
        workset="auth",
        tags=["auth"],
        summary="Remembered auth implementation plan",
        related_files=["src/auth.py"],
        related_plans=[],
        related_worksets=["auth"],
    )
    save_item(root, item)
    return item


def _write_existing_artifacts(root: Path) -> None:
    _write_project_metadata(root)
    _write_workset(root)
    paths = ForgePaths.from_root(root)
    paths.context_dir.mkdir(parents=True, exist_ok=True)
    (paths.context_dir / "auth-context-20260628.md").write_text(
        "# Auth Context\n\nContext body.\n",
        encoding="utf-8",
    )
    paths.plans_dir.mkdir(parents=True, exist_ok=True)
    (paths.plans_dir / "auth-20260628T000300.md").write_text(
        "# Auth Plan\n\nPlan body.\n",
        encoding="utf-8",
    )
    _write_memory(root)
    save_patch_content(
        root,
        """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -1 +1 @@
-old
+new
""",
        prefix="auth",
    )


def test_artifact_discovery_enumerates_existing_storage(tmp_path: Path) -> None:
    _write_existing_artifacts(tmp_path)

    artifacts = ArtifactRegistry(tmp_path).enumerate()
    artifact_types = {artifact.artifact_type for artifact in artifacts}

    assert ArtifactType.repository in artifact_types
    assert ArtifactType.workset in artifact_types
    assert ArtifactType.context_bundle in artifact_types
    assert ArtifactType.implementation_plan in artifact_types
    assert ArtifactType.memory_entry in artifact_types
    assert ArtifactType.patch in artifact_types


def test_registry_filters_by_type(tmp_path: Path) -> None:
    _write_existing_artifacts(tmp_path)
    registry = ArtifactRegistry.from_root(tmp_path)

    worksets = registry.by_type(ArtifactType.workset)

    assert [artifact.name for artifact in worksets] == ["auth"]


def test_registry_locates_artifact_by_identifier(tmp_path: Path) -> None:
    _write_existing_artifacts(tmp_path)
    registry = ArtifactRegistry(tmp_path)
    memory = registry.by_type("memory_entry")[0]

    found = registry.by_id(memory.id)

    assert found == memory


def test_metadata_loading_from_existing_formats(tmp_path: Path) -> None:
    _write_existing_artifacts(tmp_path)
    registry = ArtifactRegistry(tmp_path)

    workset = registry.by_type(ArtifactType.workset)[0]
    memory = registry.by_type(ArtifactType.memory_entry)[0]

    assert workset.created_at == "2026-06-28T00:00:00+00:00"
    assert workset.updated_at == "2026-06-28T00:01:00+00:00"
    assert workset.metadata["query"] == "authentication flow"
    assert workset.metadata["file_count"] == 1
    assert memory.metadata["tags"] == ["auth"]
    assert memory.description == "Remembered auth implementation plan"


def test_relationship_model_is_sparse_and_explicit(tmp_path: Path) -> None:
    _write_existing_artifacts(tmp_path)
    registry = ArtifactRegistry(tmp_path)
    memory = registry.by_type(ArtifactType.memory_entry)[0]

    relationships = registry.relationships(memory.id)

    assert len(relationships) == 1
    assert relationships[0].relationship_type == "derived_from_workset"
    assert relationships[0].target_id == "workset:auth"
    assert registry.related(memory.id)[0].name == "auth"


def test_partial_and_malformed_metadata_do_not_break_discovery(tmp_path: Path) -> None:
    paths = ForgePaths.from_root(tmp_path)
    paths.project_forge_dir.mkdir(parents=True, exist_ok=True)
    (paths.project_forge_dir / "project.json").write_text("{not json", encoding="utf-8")
    paths.worksets_dir.mkdir(parents=True, exist_ok=True)
    (paths.worksets_dir / "broken.json").write_text("{not json", encoding="utf-8")

    registry = ArtifactRegistry(tmp_path)
    artifacts = registry.by_type(ArtifactType.workset)

    assert len(artifacts) == 1
    assert artifacts[0].name == "broken"
    assert artifacts[0].metadata["file_count"] == 0
    assert registry.by_type(ArtifactType.repository)[0].name == tmp_path.name


def test_registry_does_not_modify_existing_files(tmp_path: Path) -> None:
    _write_workset(tmp_path)
    workset_path = tmp_path / ".forge" / "worksets" / "auth.json"
    before = json.loads(workset_path.read_text(encoding="utf-8"))

    ArtifactRegistry(tmp_path).enumerate()

    after = json.loads(workset_path.read_text(encoding="utf-8"))
    assert after == before
