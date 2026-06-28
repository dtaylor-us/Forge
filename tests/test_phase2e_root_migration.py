"""Phase 2E: root resolver migration tests.

Verifies that repo and workset commands resolve the repository root by walking
upward from the current working directory rather than using cwd directly.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from forge.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal fake git repo with files at the root."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "README.md").write_text("# Root README\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("# root source\n", encoding="utf-8")
    return tmp_path


def _make_nested(repo: Path) -> Path:
    nested = repo / "src" / "deep" / "path"
    nested.mkdir(parents=True)
    return nested


# ---------------------------------------------------------------------------
# forge repo detect — nested directory resolves to repo root
# ---------------------------------------------------------------------------


def test_repo_detect_from_nested_dir(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    nested = _make_nested(repo)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["repo", "detect"])

    # Proved by README.md appearing as an important file (only at repo root, not in nested)
    assert result.exit_code == 0
    assert "README.md" in result.output


def test_repo_detect_root_override(tmp_path):
    repo = _make_repo(tmp_path)

    result = runner.invoke(app, ["repo", "detect", "--root", str(repo)])

    assert result.exit_code == 0
    assert "README.md" in result.output


def test_repo_detect_no_git_falls_back_to_cwd(tmp_path, monkeypatch):
    (tmp_path / "file.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["repo", "detect"])

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# forge repo tree — nested directory shows root-level files
# ---------------------------------------------------------------------------


def test_repo_tree_from_nested_dir(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    nested = _make_nested(repo)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["repo", "tree", "--max-depth", "1"])

    assert result.exit_code == 0
    assert "README.md" in result.output


def test_repo_tree_root_override_beats_cwd(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "other.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.chdir(other)

    result = runner.invoke(app, ["repo", "tree", "--root", str(repo), "--max-depth", "1"])

    assert result.exit_code == 0
    assert "README.md" in result.output
    assert "other.py" not in result.output


# ---------------------------------------------------------------------------
# forge repo grep — nested directory finds root-level matches
# ---------------------------------------------------------------------------


def test_repo_grep_from_nested_dir(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    (repo / "target.py").write_text("UNIQUE_MARKER = True\n", encoding="utf-8")
    nested = _make_nested(repo)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["repo", "grep", "UNIQUE_MARKER"])

    assert result.exit_code == 0
    assert "UNIQUE_MARKER" in result.output


def test_repo_grep_root_override(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "search_me.py").write_text("FINDME = 1\n", encoding="utf-8")

    result = runner.invoke(app, ["repo", "grep", "FINDME", "--root", str(repo)])

    assert result.exit_code == 0
    assert "FINDME" in result.output


# ---------------------------------------------------------------------------
# forge repo files — nested directory lists root-level source files
# ---------------------------------------------------------------------------


def test_repo_files_from_nested_dir(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    nested = _make_nested(repo)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["repo", "files", "--ext", "py"])

    assert result.exit_code == 0
    assert "main.py" in result.output


def test_repo_files_root_override(tmp_path):
    repo = _make_repo(tmp_path)

    result = runner.invoke(app, ["repo", "files", "--root", str(repo), "--ext", "py"])

    assert result.exit_code == 0
    assert "main.py" in result.output


# ---------------------------------------------------------------------------
# forge workset suggest — nested directory ranks root-level files
# ---------------------------------------------------------------------------


def test_workset_suggest_from_nested_dir(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    (repo / "config.py").write_text("# config module\n", encoding="utf-8")
    nested = _make_nested(repo)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["workset", "suggest", "config"])

    assert result.exit_code == 0
    assert "config" in result.output


def test_workset_suggest_root_override(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "manager.py").write_text("# manager\n", encoding="utf-8")

    result = runner.invoke(app, ["workset", "suggest", "manager", "--root", str(repo)])

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# forge explain-project — nested directory resolves to repo root
# ---------------------------------------------------------------------------


def test_explain_project_has_root_option(tmp_path):
    _make_repo(tmp_path)

    result = runner.invoke(app, ["explain-project", "--help"])

    assert "--root" in result.output


# ---------------------------------------------------------------------------
# forge workset create/list/show — nested directory uses repo root for storage
# ---------------------------------------------------------------------------


def test_workset_create_from_nested_dir_writes_to_repo_root(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    (repo / "handler.py").write_text("# handler\n", encoding="utf-8")
    nested = _make_nested(repo)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["workset", "create", "my-ws", "--query", "handler"])

    assert result.exit_code == 0
    assert (repo / ".forge" / "worksets" / "my-ws.json").exists()


def test_workset_list_from_nested_dir_reads_repo_root(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    (repo / "handler.py").write_text("# handler\n", encoding="utf-8")
    # Pre-create workset via --root so it lands at repo root
    runner.invoke(
        app,
        ["workset", "create", "existing-ws", "--query", "handler", "--root", str(repo)],
    )

    nested = _make_nested(repo)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["workset", "list"])

    assert result.exit_code == 0
    assert "existing-ws" in result.output


def test_workset_show_from_nested_dir(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    (repo / "handler.py").write_text("# handler\n", encoding="utf-8")
    runner.invoke(app, ["workset", "create", "show-ws", "--query", "handler", "--root", str(repo)])

    nested = _make_nested(repo)
    monkeypatch.chdir(nested)

    result = runner.invoke(app, ["workset", "show", "show-ws"])

    assert result.exit_code == 0
    assert "show-ws" in result.output


# ---------------------------------------------------------------------------
# --root override wins over cwd in all cases
# ---------------------------------------------------------------------------


def test_root_override_wins_over_cwd(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    (repo / "override_target.py").write_text("# target\n", encoding="utf-8")

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    result = runner.invoke(app, ["repo", "files", "--root", str(repo), "--ext", "py"])

    assert result.exit_code == 0
    assert "override_target.py" in result.output


# ---------------------------------------------------------------------------
# no .git fallback — uses cwd, does not crash
# ---------------------------------------------------------------------------


def test_no_git_fallback_uses_cwd(tmp_path, monkeypatch):
    (tmp_path / "standalone.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["repo", "files", "--ext", "py"])

    assert result.exit_code == 0
    assert "standalone.py" in result.output
