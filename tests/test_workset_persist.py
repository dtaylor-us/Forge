"""Tests for Phase 2C persistent worksets."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from forge.cli.app import app
from forge.worksets.manager import (
    add_file,
    clear_workset,
    create_workset,
    get_workset,
    list_worksets,
    refresh_workset,
    remove_file,
)
from forge.worksets.store import (
    WorksetStoreError,
    exists,
    list_names,
    validate_name,
    workset_path,
    worksets_dir,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------


def test_validate_name_valid():
    validate_name("model-config")
    validate_name("my_workset")
    validate_name("abc123")


def test_validate_name_empty():
    with pytest.raises(WorksetStoreError, match="empty"):
        validate_name("")


def test_validate_name_slash():
    with pytest.raises(WorksetStoreError):
        validate_name("foo/bar")


def test_validate_name_backslash():
    with pytest.raises(WorksetStoreError):
        validate_name("foo\\bar")


def test_validate_name_dotdot():
    with pytest.raises(WorksetStoreError):
        validate_name("../etc")


def test_validate_name_space():
    with pytest.raises(WorksetStoreError):
        validate_name("my workset")


def test_candidate_to_file_entry_no_colon_in_label_does_not_duplicate() -> None:
    from forge.worksets.manager import _candidate_to_file_entry

    entry = _candidate_to_file_entry(
        SimpleNamespace(
            path=Path("calc.py"),
            score=10,
            file_category="source",
            reasons=[SimpleNamespace(label="filename matched 'calculator'", score=10)],
        ),
        Path("/repo"),
    )

    reason = entry["reasons"][0]
    assert reason["signal"] == "match"
    assert reason["detail"] == "filename matched 'calculator'"
    assert reason["signal"] != reason["detail"]


def test_candidate_to_file_entry_with_colon_label_splits_correctly() -> None:
    from forge.worksets.manager import _candidate_to_file_entry

    entry = _candidate_to_file_entry(
        SimpleNamespace(
            path=Path("calc.py"),
            score=8,
            file_category="source",
            reasons=[SimpleNamespace(label="filename:matched 'calculator'", score=8)],
        ),
        Path("/repo"),
    )

    reason = entry["reasons"][0]
    assert reason["signal"] == "filename"
    assert reason["detail"] == "matched 'calculator'"


# ---------------------------------------------------------------------------
# Store path resolution
# ---------------------------------------------------------------------------


def test_workset_path_resolution(tmp_path):
    p = workset_path(tmp_path, "my-ws")
    assert p == tmp_path / ".forge" / "worksets" / "my-ws.json"


def test_worksets_dir(tmp_path):
    d = worksets_dir(tmp_path)
    assert d == tmp_path / ".forge" / "worksets"


# ---------------------------------------------------------------------------
# Create / save / load
# ---------------------------------------------------------------------------


def _make_file(root: Path, rel: str, content: str = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_create_and_load(tmp_path):
    _make_file(tmp_path, "forge/models/manager.py", "class ModelManager: pass")
    data = create_workset(tmp_path, "test-ws", "model manager", max_results=5)
    assert data["schema_version"] == 1
    assert data["name"] == "test-ws"
    assert data["query"] == "model manager"
    assert "created_at" in data
    assert "updated_at" in data
    assert isinstance(data["files"], list)

    loaded = get_workset(tmp_path, "test-ws")
    assert loaded["name"] == "test-ws"


def test_json_shape(tmp_path):
    _make_file(tmp_path, "src/manager.py", "# manager")
    create_workset(tmp_path, "shape-ws", "manager", max_results=5)
    raw = (tmp_path / ".forge" / "worksets" / "shape-ws.json").read_text()
    obj = json.loads(raw)
    assert obj["schema_version"] == 1
    if obj["files"]:
        f = obj["files"][0]
        assert "path" in f
        assert "score" in f
        assert "category" in f
        assert "reasons" in f
        assert "manual" in f
        if f["reasons"]:
            r = f["reasons"][0]
            assert "signal" in r
            assert "detail" in r
            assert "points" in r


def test_create_duplicate_fails(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    create_workset(tmp_path, "dup-ws", "foo")
    with pytest.raises(WorksetStoreError, match="already exists"):
        create_workset(tmp_path, "dup-ws", "foo")


def test_create_force_overwrite(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    create_workset(tmp_path, "dup-ws", "foo")
    data = create_workset(tmp_path, "dup-ws", "new query", force=True)
    assert data["query"] == "new query"


# ---------------------------------------------------------------------------
# exists / list_names
# ---------------------------------------------------------------------------


def test_exists_false(tmp_path):
    assert not exists(tmp_path, "missing")


def test_exists_true(tmp_path):
    _make_file(tmp_path, "src/a.py", "")
    create_workset(tmp_path, "my-ws", "a")
    assert exists(tmp_path, "my-ws")


def test_list_names_empty(tmp_path):
    assert list_names(tmp_path) == []


def test_list_names(tmp_path):
    _make_file(tmp_path, "src/a.py", "")
    create_workset(tmp_path, "alpha", "a")
    create_workset(tmp_path, "beta", "b")
    names = list_names(tmp_path)
    assert names == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# add_file
# ---------------------------------------------------------------------------


def test_add_file(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    _make_file(tmp_path, "README.md", "readme")
    create_workset(tmp_path, "ws", "foo")
    data = add_file(tmp_path, "ws", "README.md")
    paths = [f["path"] for f in data["files"]]
    assert "README.md" in paths
    manual = next(f for f in data["files"] if f["path"] == "README.md")
    assert manual["manual"] is True


def test_add_file_not_duplicated(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    _make_file(tmp_path, "README.md", "")
    create_workset(tmp_path, "ws", "foo")
    add_file(tmp_path, "ws", "README.md")
    data = add_file(tmp_path, "ws", "README.md")
    paths = [f["path"] for f in data["files"]]
    assert paths.count("README.md") == 1


def test_add_file_outside_root(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    create_workset(tmp_path, "ws", "foo")
    with pytest.raises(WorksetStoreError, match="outside"):
        add_file(tmp_path, "ws", "/etc/passwd")


def test_add_file_missing(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    create_workset(tmp_path, "ws", "foo")
    with pytest.raises(WorksetStoreError, match="does not exist"):
        add_file(tmp_path, "ws", "nonexistent.py")


# ---------------------------------------------------------------------------
# remove_file
# ---------------------------------------------------------------------------


def test_remove_file(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    _make_file(tmp_path, "README.md", "")
    create_workset(tmp_path, "ws", "foo")
    add_file(tmp_path, "ws", "README.md")
    data = remove_file(tmp_path, "ws", "README.md")
    paths = [f["path"] for f in data["files"]]
    assert "README.md" not in paths


def test_remove_file_not_present_is_noop(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    create_workset(tmp_path, "ws", "foo")
    before = get_workset(tmp_path, "ws")
    data = remove_file(tmp_path, "ws", "nonexistent.py")
    assert len(data["files"]) == len(before["files"])


# ---------------------------------------------------------------------------
# clear / delete
# ---------------------------------------------------------------------------


def test_clear_workset(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    create_workset(tmp_path, "ws", "foo")
    assert exists(tmp_path, "ws")
    clear_workset(tmp_path, "ws")
    assert not exists(tmp_path, "ws")


def test_clear_missing_raises(tmp_path):
    with pytest.raises(WorksetStoreError, match="not found"):
        clear_workset(tmp_path, "ghost")


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


def test_refresh_workset(tmp_path):
    _make_file(tmp_path, "src/manager.py", "manager content")
    create_workset(tmp_path, "ws", "manager", max_results=5)
    data = refresh_workset(tmp_path, "ws")
    assert "updated_at" in data
    assert isinstance(data["files"], list)


def test_refresh_preserves_manual_files(tmp_path):
    _make_file(tmp_path, "src/foo.py", "foo")
    _make_file(tmp_path, "README.md", "readme")
    create_workset(tmp_path, "ws", "foo")
    add_file(tmp_path, "ws", "README.md")

    data = refresh_workset(tmp_path, "ws")
    paths = [f["path"] for f in data["files"]]
    assert "README.md" in paths
    manual = next((f for f in data["files"] if f["path"] == "README.md"), None)
    assert manual is not None
    assert manual["manual"] is True


def test_refresh_drops_missing_manual_files(tmp_path):
    _make_file(tmp_path, "src/foo.py", "foo")
    gone = _make_file(tmp_path, "transient.py", "gone")
    create_workset(tmp_path, "ws", "foo")
    # Manually inject a file entry that won't be re-suggested
    data = get_workset(tmp_path, "ws")
    data["files"].append(
        {
            "path": "transient.py",
            "score": 0,
            "category": "source",
            "reasons": [{"signal": "manual", "detail": "manually added", "points": 0}],
            "manual": True,
        }
    )
    from forge.worksets.store import save

    save(tmp_path, data)

    gone.unlink()
    refreshed = refresh_workset(tmp_path, "ws")
    paths = [f["path"] for f in refreshed["files"]]
    assert "transient.py" not in paths


# ---------------------------------------------------------------------------
# Relative path normalization
# ---------------------------------------------------------------------------


def test_relative_path_posix(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    _make_file(tmp_path, "sub/bar.py", "")
    create_workset(tmp_path, "ws", "foo")
    add_file(tmp_path, "ws", "sub/bar.py")
    data = get_workset(tmp_path, "ws")
    paths = [f["path"] for f in data["files"]]
    assert "sub/bar.py" in paths
    assert all("\\" not in p for p in paths)


# ---------------------------------------------------------------------------
# list_worksets
# ---------------------------------------------------------------------------


def test_list_worksets(tmp_path):
    _make_file(tmp_path, "src/a.py", "")
    create_workset(tmp_path, "alpha", "a")
    create_workset(tmp_path, "beta", "b")
    names = list_worksets(tmp_path)
    assert "alpha" in names
    assert "beta" in names


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def test_cli_workset_create(tmp_path):
    _make_file(tmp_path, "src/manager.py", "manager")
    result = runner.invoke(
        app,
        ["workset", "create", "my-ws", "--query", "manager", "--root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "my-ws" in result.output


def test_cli_workset_create_duplicate(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    runner.invoke(app, ["workset", "create", "my-ws", "--query", "foo", "--root", str(tmp_path)])
    result = runner.invoke(
        app,
        ["workset", "create", "my-ws", "--query", "foo", "--root", str(tmp_path)],
    )
    assert result.exit_code == 1


def test_cli_workset_create_force(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    runner.invoke(app, ["workset", "create", "my-ws", "--query", "foo", "--root", str(tmp_path)])
    result = runner.invoke(
        app,
        ["workset", "create", "my-ws", "--query", "bar", "--root", str(tmp_path), "--force"],
    )
    assert result.exit_code == 0, result.output


def test_cli_workset_list(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    runner.invoke(app, ["workset", "create", "alpha", "--query", "foo", "--root", str(tmp_path)])
    result = runner.invoke(app, ["workset", "list", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "alpha" in result.output


def test_cli_workset_list_empty(tmp_path):
    result = runner.invoke(app, ["workset", "list", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "No worksets" in result.output


def test_cli_workset_show(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    runner.invoke(app, ["workset", "create", "show-ws", "--query", "foo", "--root", str(tmp_path)])
    result = runner.invoke(app, ["workset", "show", "show-ws", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "show-ws" in result.output


def test_cli_workset_show_reasons_omit_generic_match_prefix(tmp_path):
    """Regression for I-10.

    `_candidate_to_file_entry` stores a generic "match" signal for reasons
    whose label has no natural "signal:detail" split (the common case for
    filename/content-match reasons). `forge workset show` used to render
    that as a literal "match:<detail>" prefix, which `forge workset suggest`
    (rendering the same underlying label directly) never showed. The CLI
    display should now omit the redundant "match:" prefix.
    """
    _make_file(tmp_path, "src/calculator.py", "")
    runner.invoke(
        app,
        ["workset", "create", "calc-ws", "--query", "calculator", "--root", str(tmp_path)],
    )
    result = runner.invoke(app, ["workset", "show", "calc-ws", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "match:" not in result.output.lower()


def test_cli_workset_show_json(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    runner.invoke(app, ["workset", "create", "show-ws", "--query", "foo", "--root", str(tmp_path)])
    result = runner.invoke(app, ["workset", "show", "show-ws", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["name"] == "show-ws"


def test_cli_workset_show_surfaces_linked_decision(tmp_path):
    """Dogfood report recommendation: surface linked decisions/investigations
    inline in `forge workset show`, instead of leaving them discoverable only
    via `forge memory timeline`/`forge memory search`.
    """
    _make_file(tmp_path, "src/foo.py", "")
    runner.invoke(app, ["workset", "create", "memo-ws", "--query", "foo", "--root", str(tmp_path)])
    runner.invoke(
        app,
        [
            "decision",
            "create",
            "Use dependency injection",
            "--workset",
            "memo-ws",
            "--root",
            str(tmp_path),
        ],
    )

    result = runner.invoke(app, ["workset", "show", "memo-ws", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Linked Memory" in result.output
    assert "Use dependency injection" in result.output


def test_cli_workset_show_json_includes_linked_memory(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    runner.invoke(app, ["workset", "create", "memo-ws", "--query", "foo", "--root", str(tmp_path)])
    runner.invoke(
        app,
        [
            "investigation",
            "create",
            "Why search is slow",
            "--workset",
            "memo-ws",
            "--root",
            str(tmp_path),
        ],
    )

    result = runner.invoke(
        app, ["workset", "show", "memo-ws", "--root", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert len(parsed["memory"]) == 1
    assert parsed["memory"][0]["title"] == "Why search is slow"
    assert parsed["memory"][0]["type"] == "investigation"


def test_cli_workset_show_no_memory_section_when_none_linked(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    runner.invoke(
        app, ["workset", "create", "no-memo-ws", "--query", "foo", "--root", str(tmp_path)]
    )

    result = runner.invoke(app, ["workset", "show", "no-memo-ws", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Linked Memory" not in result.output


def test_cli_workset_add(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    _make_file(tmp_path, "README.md", "readme")
    runner.invoke(app, ["workset", "create", "ws", "--query", "foo", "--root", str(tmp_path)])
    result = runner.invoke(app, ["workset", "add", "ws", "README.md", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Added" in result.output


def test_cli_workset_remove(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    _make_file(tmp_path, "README.md", "")
    runner.invoke(app, ["workset", "create", "ws", "--query", "foo", "--root", str(tmp_path)])
    runner.invoke(app, ["workset", "add", "ws", "README.md", "--root", str(tmp_path)])
    result = runner.invoke(app, ["workset", "remove", "ws", "README.md", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Removed" in result.output


def test_cli_workset_refresh(tmp_path):
    _make_file(tmp_path, "src/foo.py", "foo content")
    runner.invoke(app, ["workset", "create", "ws", "--query", "foo", "--root", str(tmp_path)])
    result = runner.invoke(app, ["workset", "refresh", "ws", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Refreshed" in result.output


def test_cli_workset_clear_yes(tmp_path):
    _make_file(tmp_path, "src/foo.py", "")
    runner.invoke(app, ["workset", "create", "ws", "--query", "foo", "--root", str(tmp_path)])
    result = runner.invoke(app, ["workset", "clear", "ws", "--root", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert "Deleted" in result.output
    assert not exists(tmp_path, "ws")
