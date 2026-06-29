"""Tests for GitService and git CLI commands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from forge.cli.app import app
from forge.git.service import GitService, GitServiceError

runner = CliRunner()


@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    """Initialize a bare git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    (tmp_path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path


def test_not_a_git_repo(tmp_path: Path) -> None:
    svc = GitService(tmp_path)
    assert not svc.is_git_repository()
    status = svc.status()
    assert not status.is_git_repository


def test_clean_repo(tmp_git_repo: Path) -> None:
    svc = GitService(tmp_git_repo)
    assert svc.is_git_repository()
    status = svc.status()
    assert status.is_git_repository
    assert status.clean
    assert status.staged_files == []
    assert status.modified_files == []
    assert status.deleted_files == []
    assert status.untracked_files == []


def test_dirty_repo_untracked(tmp_git_repo: Path) -> None:
    (tmp_git_repo / "notes.txt").write_text("hello")
    svc = GitService(tmp_git_repo)
    status = svc.status()
    assert not status.clean
    assert "notes.txt" in status.untracked_files


def test_dirty_repo_modified(tmp_git_repo: Path) -> None:
    (tmp_git_repo / "README.md").write_text("changed\n")
    svc = GitService(tmp_git_repo)
    status = svc.status()
    assert not status.clean
    assert "README.md" in status.modified_files


def test_staged_file(tmp_git_repo: Path) -> None:
    (tmp_git_repo / "new.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "new.py"], cwd=tmp_git_repo, check=True, capture_output=True)
    svc = GitService(tmp_git_repo)
    status = svc.status()
    assert not status.clean
    assert "new.py" in status.staged_files


def test_branch_detection(tmp_git_repo: Path) -> None:
    svc = GitService(tmp_git_repo)
    branch = svc.branch()
    assert branch in ("main", "master")


def test_status_to_dict(tmp_git_repo: Path) -> None:
    svc = GitService(tmp_git_repo)
    d = svc.status().to_dict()
    assert "is_git_repository" in d
    assert "branch" in d
    assert "commit" in d
    assert "clean" in d
    assert "staged_files" in d
    assert "modified_files" in d
    assert "deleted_files" in d
    assert "untracked_files" in d


# CLI tests

def test_cli_git_status_not_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["git", "status"])
    assert result.exit_code == 1
    assert "Not a git repository" in result.stdout


def test_cli_git_status_json_not_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["git", "status", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["is_git_repository"] is False


def test_cli_git_status_clean(tmp_git_repo: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_git_repo)
    result = runner.invoke(app, ["git", "status"])
    assert result.exit_code == 0
    assert "Branch:" in result.stdout
    assert "Commit:" in result.stdout
    assert "Clean: true" in result.stdout


def test_cli_git_status_json_clean(tmp_git_repo: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_git_repo)
    result = runner.invoke(app, ["git", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["is_git_repository"] is True
    assert data["clean"] is True


def test_cli_git_branch(tmp_git_repo: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_git_repo)
    result = runner.invoke(app, ["git", "branch"])
    assert result.exit_code == 0
    assert "Current branch:" in result.stdout


def test_cli_git_branch_not_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["git", "branch"])
    assert result.exit_code == 1


def test_cli_git_branch_json(tmp_git_repo: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_git_repo)
    result = runner.invoke(app, ["git", "branch", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["is_git_repository"] is True
    assert data["branch"] is not None
