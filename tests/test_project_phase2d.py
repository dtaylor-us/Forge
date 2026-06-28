"""Tests for Phase 2D: repository identity and project metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from forge.cli.app import app
from forge.project.initializer import initialize_project
from forge.project.metadata import build_metadata, load_metadata, save_metadata
from forge.project.paths import ForgePaths, global_forge_dir
from forge.project.resolver import ResolvedRoot, resolve_root

runner = CliRunner()

# ---------------------------------------------------------------------------
# resolver
# ---------------------------------------------------------------------------


def test_resolve_root_from_git_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = resolve_root(tmp_path)
    assert result.root == tmp_path
    assert result.git_detected is True


def test_resolve_root_from_nested_subdirectory(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "main"
    nested.mkdir(parents=True)
    result = resolve_root(nested)
    assert result.root == tmp_path
    assert result.git_detected is True


def test_resolve_root_no_git(tmp_path: Path) -> None:
    result = resolve_root(tmp_path)
    assert result.root == tmp_path
    assert result.git_detected is False


def test_resolve_root_override(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (other / ".git").mkdir()
    result = resolve_root(tmp_path, override=other)
    assert result.root == other
    assert result.git_detected is True


def test_resolve_root_override_no_git(tmp_path: Path) -> None:
    result = resolve_root(override=tmp_path)
    assert result.root == tmp_path
    assert result.git_detected is False


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------


def test_global_forge_dir() -> None:
    g = global_forge_dir()
    assert g == Path.home() / ".forge"


def test_forge_paths_from_root(tmp_path: Path) -> None:
    paths = ForgePaths.from_root(tmp_path)
    assert paths.repo_root == tmp_path
    assert paths.project_forge_dir == tmp_path / ".forge"
    assert paths.worksets_dir == tmp_path / ".forge" / "worksets"
    assert paths.summaries_dir == tmp_path / ".forge" / "summaries"
    assert paths.context_dir == tmp_path / ".forge" / "context"
    assert paths.architecture_dir == tmp_path / ".forge" / "architecture"
    assert paths.sessions_dir == tmp_path / ".forge" / "sessions"
    assert paths.cache_dir == tmp_path / ".forge" / "cache"
    assert paths.global_forge_dir == Path.home() / ".forge"
    assert paths.global_config_path == Path.home() / ".forge" / "config.yaml"


def test_forge_paths_to_dict(tmp_path: Path) -> None:
    paths = ForgePaths.from_root(tmp_path)
    d = paths.to_dict()
    assert d["repo_root"] == str(tmp_path)
    assert d["project_forge_dir"] == str(tmp_path / ".forge")
    assert "global_forge_dir" in d
    assert "worksets_dir" in d


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------


def test_build_metadata_shape(tmp_path: Path) -> None:
    meta = build_metadata(tmp_path, "myproject")
    assert meta["schema_version"] == 1
    assert meta["project_name"] == "myproject"
    assert meta["root"] == str(tmp_path)
    assert "created_at" in meta
    assert "updated_at" in meta
    assert "forge_version" in meta
    assert "detected" in meta


def test_save_and_load_metadata(tmp_path: Path) -> None:
    forge_dir = tmp_path / ".forge"
    meta = build_metadata(tmp_path, "proj")
    save_metadata(forge_dir, meta)
    loaded = load_metadata(forge_dir)
    assert loaded is not None
    assert loaded["project_name"] == "proj"


def test_load_metadata_missing(tmp_path: Path) -> None:
    forge_dir = tmp_path / ".forge"
    assert load_metadata(forge_dir) is None


# ---------------------------------------------------------------------------
# initializer
# ---------------------------------------------------------------------------


def _git_root(tmp_path: Path) -> ResolvedRoot:
    (tmp_path / ".git").mkdir()
    return ResolvedRoot(root=tmp_path, git_detected=True)


def test_initialize_creates_subdirs(tmp_path: Path) -> None:
    resolved = _git_root(tmp_path)
    initialize_project(resolved)
    forge_dir = tmp_path / ".forge"
    for sub in ("worksets", "summaries", "context", "architecture", "sessions", "cache"):
        assert (forge_dir / sub).is_dir(), f"Missing subdir: {sub}"


def test_initialize_creates_project_json(tmp_path: Path) -> None:
    resolved = _git_root(tmp_path)
    initialize_project(resolved)
    meta_file = tmp_path / ".forge" / "project.json"
    assert meta_file.exists()
    data = json.loads(meta_file.read_text())
    assert data["schema_version"] == 1
    assert data["root"] == str(tmp_path)


def test_initialize_already_exists_raises(tmp_path: Path) -> None:
    resolved = _git_root(tmp_path)
    initialize_project(resolved)
    with pytest.raises(FileExistsError):
        initialize_project(resolved)


def test_initialize_force_overwrites(tmp_path: Path) -> None:
    resolved = _git_root(tmp_path)
    initialize_project(resolved)
    result2 = initialize_project(resolved, force=True)
    assert result2.already_existed is True
    assert result2.forced is True


def test_initialize_force_preserves_created_at(tmp_path: Path) -> None:
    resolved = _git_root(tmp_path)
    initialize_project(resolved)
    meta_before = load_metadata(tmp_path / ".forge")
    assert meta_before is not None
    created_at_before = meta_before["created_at"]
    initialize_project(resolved, force=True)
    meta_after = load_metadata(tmp_path / ".forge")
    assert meta_after is not None
    assert meta_after["created_at"] == created_at_before


def test_initialize_already_existed_flag(tmp_path: Path) -> None:
    resolved = _git_root(tmp_path)
    r1 = initialize_project(resolved)
    assert r1.already_existed is False
    r2 = initialize_project(resolved, force=True)
    assert r2.already_existed is True


# ---------------------------------------------------------------------------
# CLI: forge init
# ---------------------------------------------------------------------------


def test_cli_init(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = runner.invoke(app, ["init", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Initialized" in result.output
    assert (tmp_path / ".forge" / "project.json").exists()


def test_cli_init_force(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    result = runner.invoke(app, ["init", "--force", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Reinitialized" in result.output


def test_cli_init_already_exists_no_force(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    result = runner.invoke(app, ["init", "--root", str(tmp_path)])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# CLI: forge project root
# ---------------------------------------------------------------------------


def test_cli_project_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = runner.invoke(app, ["project", "root", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert str(tmp_path) in result.output.replace("\n", "")


def test_cli_project_root_nested(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    result = runner.invoke(app, ["project", "root", "--root", str(nested)])
    assert result.exit_code == 0
    # --root is an override, so nested itself is returned
    assert str(nested) in result.output.replace("\n", "")


# ---------------------------------------------------------------------------
# CLI: forge project info
# ---------------------------------------------------------------------------


def test_cli_project_info_uninitialized(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = runner.invoke(app, ["project", "info", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "False" in result.output  # initialized: False


def test_cli_project_info_initialized(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    result = runner.invoke(app, ["project", "info", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "True" in result.output  # initialized: True


def test_cli_project_info_json(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    result = runner.invoke(app, ["project", "info", "--json", "--root", str(tmp_path)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["initialized"] is True
    assert data["schema_version"] == 1
    assert "repo_root" in data
    assert "project_forge_dir" in data


def test_cli_project_info_json_uninitialized(tmp_path: Path) -> None:
    result = runner.invoke(app, ["project", "info", "--json", "--root", str(tmp_path)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["initialized"] is False
    assert data["git_detected"] is False


# ---------------------------------------------------------------------------
# CLI: forge project paths
# ---------------------------------------------------------------------------


def test_cli_project_paths(tmp_path: Path) -> None:
    result = runner.invoke(app, ["project", "paths", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert ".forge" in result.output


def test_cli_project_paths_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["project", "paths", "--json", "--root", str(tmp_path)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["repo_root"] == str(tmp_path)
    assert "worksets_dir" in data
    assert "global_forge_dir" in data
    assert "global_config_path" in data
