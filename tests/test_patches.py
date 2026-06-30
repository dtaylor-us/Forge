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
    realign_patch_hunk_headers,
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


# ---------------------------------------------------------------------------
# realign_patch_hunk_headers
# ---------------------------------------------------------------------------


def _write_file(root: Path, rel: str, lines: list[str]) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_realign_correct_position_unchanged(tmp_path: Path) -> None:
    """A patch with a correct starting position is passed through untouched."""
    _write_file(tmp_path, "src/mod.py", ["a", "b", "c", "d", "e"])
    patch = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -2,2 +2,3 @@\n"
        " b\n"
        " c\n"
        "+x\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    assert corrected == patch
    assert notes == []


def test_realign_fixes_wrong_start_position(tmp_path: Path) -> None:
    """A hunk with wrong old_start but correct context content gets repositioned."""
    _write_file(tmp_path, "src/mod.py", ["a", "b", "c", "d", "e", "f"])
    # Content "c" and "d" are at lines 3–4, but the hunk header claims line 1.
    patch = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -1,2 +1,3 @@\n"  # wrong: should be -3,2 +3,3
        " c\n"
        " d\n"
        "+NEW\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    assert "@@ -3,2 +3,3 @@" in corrected
    assert len(notes) == 1
    assert "src/mod.py" in notes[0]
    assert "1" in notes[0]  # original wrong position
    assert "3" in notes[0]  # corrected position


def test_realign_preserves_hunk_suffix(tmp_path: Path) -> None:
    """Method-name suffix after '@@' is preserved during realignment."""
    _write_file(tmp_path, "src/Foo.java", ["public class Foo {", "void bar() {", "}", "}"])
    patch = (
        "diff --git a/src/Foo.java b/src/Foo.java\n"
        "--- a/src/Foo.java\n"
        "+++ b/src/Foo.java\n"
        "@@ -99,2 +99,3 @@ public class Foo {\n"  # wrong position
        " void bar() {\n"
        " }\n"
        "+// added\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    assert "@@ -2,2 +2,3 @@ public class Foo {" in corrected
    assert notes


def test_realign_no_change_when_content_not_in_file(tmp_path: Path) -> None:
    """If the hunk's context lines appear nowhere in the file, leave it unchanged."""
    _write_file(tmp_path, "src/mod.py", ["x", "y", "z"])
    patch = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -5,2 +5,3 @@\n"
        " totally\n"
        " nonexistent\n"
        "+addition\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    assert corrected == patch
    assert notes == []


def test_realign_no_change_when_content_ambiguous(tmp_path: Path) -> None:
    """If the context lines appear more than once, leave the hunk unchanged."""
    _write_file(tmp_path, "src/mod.py", ["a", "b", "a", "b", "c"])
    patch = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -10,2 +10,3 @@\n"  # wrong, but ambiguous: "a","b" at lines 1 AND 3
        " a\n"
        " b\n"
        "+new\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    assert corrected == patch
    assert notes == []


def test_realign_pure_insertion_hunk_unchanged(tmp_path: Path) -> None:
    """A hunk with no old-file lines (pure insertion) is left untouched."""
    _write_file(tmp_path, "src/mod.py", ["a", "b", "c"])
    patch = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -99,0 +99,2 @@\n"
        "+line1\n"
        "+line2\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    assert corrected == patch
    assert notes == []


def test_realign_missing_file_unchanged(tmp_path: Path) -> None:
    """If the target file does not exist on disk, the patch passes through unchanged."""
    patch = (
        "diff --git a/missing.py b/missing.py\n"
        "--- a/missing.py\n"
        "+++ b/missing.py\n"
        "@@ -1,2 +1,3 @@\n"
        " a\n"
        " b\n"
        "+c\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    assert corrected == patch
    assert notes == []


def test_realign_multiple_hunks_same_file(tmp_path: Path) -> None:
    """Multiple hunks in one file are each corrected independently."""
    _write_file(
        tmp_path,
        "src/mod.py",
        ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
    )
    # Hunk 1: context "a","b" is at lines 1-2 — stated correctly.
    # Hunk 2: context "i","j" is at lines 9-10 — stated wrong (says line 3).
    patch = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -1,2 +1,3 @@\n"
        " a\n"
        " b\n"
        "+NEW1\n"
        "@@ -3,2 +4,3 @@\n"  # wrong: "i","j" are actually at lines 9-10
        " i\n"
        " j\n"
        "+NEW2\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    # Hunk 1 was already correct — unchanged.
    assert "@@ -1,2 +1,3 @@" in corrected
    # Hunk 2 should be realigned to line 9.
    assert "@@ -9,2 +10,3 @@" in corrected
    assert len(notes) == 1
    assert "9" in notes[0]


# ---------------------------------------------------------------------------
# Anchor-line realignment tests
# ---------------------------------------------------------------------------


def test_anchor_realign_fixes_shifted_hunk(tmp_path: Path) -> None:
    """Hunk shifted N lines but with correct content is realigned via anchor lines."""
    # Simulate TacticsController pattern: file has 2 extra lines in method sig
    # that push the body down. The model generates context starting 2 lines too early.
    file_lines = [
        "    public ResponseEntity<Summary> getSummary(",
        "            @PathVariable Long id,",
        "            @AuthenticationPrincipal String userId) {",  # extra line added
        "",                                                        # extra blank line
        "        Summary summary = service.getSummary(id);",
        "        return ResponseEntity.ok(summary);",
        "    }",
        "",
        "}",
    ]
    _write_file(tmp_path, "src/Controller.java", file_lines)

    # Model generates patch starting at line 3 (the body), but body is really at line 5.
    patch = (
        "diff --git a/src/Controller.java b/src/Controller.java\n"
        "--- a/src/Controller.java\n"
        "+++ b/src/Controller.java\n"
        "@@ -3,5 +3,6 @@\n"   # wrong: model thinks body starts at line 3
        "         Summary summary = service.getSummary(id);\n"
        "         return ResponseEntity.ok(summary);\n"
        "     }\n"
        " \n"
        " }\n"
        "+// end\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)

    # Should realign from line 3 to line 5 (delta = +2)
    assert "@@ -5," in corrected
    assert len(notes) == 1
    assert "anchor-line" in notes[0]
    assert "5" in notes[0]


def test_anchor_realign_trivial_only_block_not_realigned(tmp_path: Path) -> None:
    """A hunk whose old-block has only trivial lines (brackets, blank) is not anchor-realigned."""
    file_lines = ["class Foo {", "}", "class Bar {", "}"]
    _write_file(tmp_path, "src/mod.java", file_lines)

    # Old-block is just "}" — too trivial to anchor on.
    patch = (
        "diff --git a/src/mod.java b/src/mod.java\n"
        "--- a/src/mod.java\n"
        "+++ b/src/mod.java\n"
        "@@ -99,1 +99,2 @@\n"
        " }\n"
        "+// comment\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    assert corrected == patch
    assert notes == []


def test_anchor_realign_ambiguous_anchor_not_realigned(tmp_path: Path) -> None:
    """If a distinctive line appears more than once, it is not used as an anchor."""
    # Same method body repeated in two places (e.g. overloads) → ambiguous anchor.
    body_line = "        return ResponseEntity.ok(service.get(id));"
    file_lines = [
        "    public ResponseEntity<?> getA(Long id) {",
        body_line,
        "    }",
        "    public ResponseEntity<?> getB(Long id) {",
        body_line,
        "    }",
    ]
    _write_file(tmp_path, "src/Ctrl.java", file_lines)

    patch = (
        "diff --git a/src/Ctrl.java b/src/Ctrl.java\n"
        "--- a/src/Ctrl.java\n"
        "+++ b/src/Ctrl.java\n"
        "@@ -50,2 +50,3 @@\n"  # wrong position, but body_line is ambiguous
        f" {body_line}\n"
        "     }\n"
        "+// new\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    assert corrected == patch
    assert notes == []


def test_anchor_realign_two_anchors_must_agree(tmp_path: Path) -> None:
    """When two distinctive lines suggest conflicting deltas, no realignment occurs."""
    file_lines = [
        "    String alpha = compute();",   # line 1 — anchor A at file idx 0
        "    String beta = transform();",  # line 2 — anchor B at file idx 1
        "    // gap",
        "    String alpha = compute();",   # duplicate! makes anchor A ambiguous
    ]
    _write_file(tmp_path, "src/mod.java", file_lines)

    # Model places alpha at line 10 (delta would be -9 from idx 0),
    # but alpha is duplicated so it won't be used as an anchor.
    # beta appears once (idx 1); delta from stated pos 11 = 1 - 10 = -9.
    # Only one non-ambiguous anchor (beta) — single vote, should still realign.
    patch = (
        "diff --git a/src/mod.java b/src/mod.java\n"
        "--- a/src/mod.java\n"
        "+++ b/src/mod.java\n"
        "@@ -10,2 +10,3 @@\n"
        "     String alpha = compute();\n"
        "     String beta = transform();\n"
        "+// new\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    # beta is unique, so single-anchor realignment should fire.
    # beta is at file idx 1 (1-based: 2), expected at block_idx=1.
    # delta = 1 - 9 = -8, new_old_start = 10 + (-8) = 2
    assert "@@ -2," in corrected


def test_anchor_realign_note_mentions_anchor_line(tmp_path: Path) -> None:
    """Realignment note includes 'anchor-line' to distinguish from full-block realignment."""
    file_lines = [
        "    void setup() {",
        "        this.service = new ServiceImpl();",
        "    }",
        "    void doWork() {",
        "        this.service.execute();",
        "    }",
    ]
    _write_file(tmp_path, "src/Thing.java", file_lines)

    # Patch says line 10 but body is at line 5.
    patch = (
        "diff --git a/src/Thing.java b/src/Thing.java\n"
        "--- a/src/Thing.java\n"
        "+++ b/src/Thing.java\n"
        "@@ -10,2 +10,3 @@\n"
        "         this.service.execute();\n"
        "     }\n"
        "+// trailing comment\n"
    )
    corrected, notes = realign_patch_hunk_headers(tmp_path, patch)
    assert notes
    assert any("anchor-line" in n for n in notes)
