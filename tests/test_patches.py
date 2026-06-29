"""Tests for patch storage and validation."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from forge.cli.app import app
from forge.patches.service import (
    ensure_patch_dir,
    extract_affected_files,
    list_patches,
    read_patch,
    validate_patch_content,
)

runner = CliRunner()


GIT_DIFF = """diff --git a/forge/example.py b/forge/example.py
index 1111111..2222222 100644
--- a/forge/example.py
+++ b/forge/example.py
@@ -1 +1 @@
-old
+new
"""

UNIFIED_DIFF = """--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-# Old
+# New
"""


def test_valid_git_diff_with_diff_git() -> None:
    valid, errors, affected_files = validate_patch_content(GIT_DIFF)

    assert valid is True
    assert errors == []
    assert affected_files == ["forge/example.py"]


def test_valid_unified_diff_with_headers() -> None:
    valid, errors, affected_files = validate_patch_content(UNIFIED_DIFF)

    assert valid is True
    assert errors == []
    assert affected_files == ["README.md"]


def test_invalid_prose() -> None:
    valid, errors, affected_files = validate_patch_content("This change updates the README.")

    assert valid is False
    assert affected_files == []
    assert any("raw diff" in error for error in errors)
    assert any("hunk marker" in error for error in errors)


def test_invalid_empty_file() -> None:
    valid, errors, affected_files = validate_patch_content("")

    assert valid is False
    assert errors == ["Patch is empty."]
    assert affected_files == []


def test_invalid_markdown_fenced_diff_with_extra_prose() -> None:
    content = f"Here is the patch:\n\n```diff\n{UNIFIED_DIFF}```\n"

    valid, errors, _affected_files = validate_patch_content(content)

    assert valid is False
    assert any("Markdown fenced" in error for error in errors)
    assert any("prose" in error for error in errors)


def test_affected_file_extraction_from_diff_git() -> None:
    assert extract_affected_files(GIT_DIFF) == ["forge/example.py"]


def test_affected_file_extraction_from_unified_headers() -> None:
    assert extract_affected_files(UNIFIED_DIFF) == ["README.md"]


def test_patch_directory_creation(tmp_path: Path) -> None:
    directory = ensure_patch_dir(tmp_path)

    assert directory == tmp_path / ".forge" / "patches"
    assert directory.is_dir()


def test_patch_list_returns_saved_patches(tmp_path: Path) -> None:
    directory = ensure_patch_dir(tmp_path)
    (directory / "example.patch").write_text(GIT_DIFF, encoding="utf-8")

    patches = list_patches(tmp_path)

    assert [patch.name for patch in patches] == ["example.patch"]
    assert patches[0].valid is True
    assert patches[0].affected_files == ["forge/example.py"]


def test_patch_show_resolves_saved_patch_names(tmp_path: Path) -> None:
    directory = ensure_patch_dir(tmp_path)
    (directory / "example.patch").write_text(GIT_DIFF, encoding="utf-8")

    assert read_patch(tmp_path, "example.patch") == GIT_DIFF


def test_cli_patch_list_json(tmp_path: Path) -> None:
    directory = ensure_patch_dir(tmp_path)
    (directory / "example.patch").write_text(GIT_DIFF, encoding="utf-8")

    result = runner.invoke(app, ["patch", "list", "--root", str(tmp_path), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["name"] == "example.patch"
    assert data[0]["valid"] is True


def test_cli_patch_validate_invalid_exits_one(tmp_path: Path) -> None:
    path = tmp_path / "not-a.patch"
    path.write_text("Plain prose.\n", encoding="utf-8")

    result = runner.invoke(app, ["patch", "validate", str(path), "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "invalid" in result.output


def test_cli_patch_show_prints_content(tmp_path: Path) -> None:
    directory = ensure_patch_dir(tmp_path)
    (directory / "example.patch").write_text(GIT_DIFF, encoding="utf-8")

    result = runner.invoke(app, ["patch", "show", "example.patch", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "diff --git a/forge/example.py b/forge/example.py" in result.output
