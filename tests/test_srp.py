"""Tests for the forge.srp package (parser, applier, and integration)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from forge.srp import (
    SearchReplaceBlock,
    apply_blocks,
    parse_search_replace_blocks,
)

# forge.execution requires Python 3.11+ (datetime.UTC).
_requires_py311 = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="forge.execution requires Python 3.11+ (datetime.UTC)",
)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParseSearchReplaceBlocks:
    def test_single_block(self) -> None:
        content = textwrap.dedent("""\
            src/Foo.java
            <<<<<<< SEARCH
            old line
            =======
            new line
            >>>>>>> REPLACE
        """)
        blocks = parse_search_replace_blocks(content)
        assert len(blocks) == 1
        assert blocks[0].file_path == "src/Foo.java"
        assert blocks[0].search == "old line"
        assert blocks[0].replace == "new line"

    def test_multiple_blocks_same_file(self) -> None:
        content = textwrap.dedent("""\
            src/Foo.java
            <<<<<<< SEARCH
            alpha
            =======
            ALPHA
            >>>>>>> REPLACE

            src/Foo.java
            <<<<<<< SEARCH
            beta
            =======
            BETA
            >>>>>>> REPLACE
        """)
        blocks = parse_search_replace_blocks(content)
        assert len(blocks) == 2
        assert blocks[0].search == "alpha"
        assert blocks[1].search == "beta"

    def test_multiple_files(self) -> None:
        content = textwrap.dedent("""\
            src/Foo.java
            <<<<<<< SEARCH
            foo
            =======
            FOO
            >>>>>>> REPLACE

            src/Bar.java
            <<<<<<< SEARCH
            bar
            =======
            BAR
            >>>>>>> REPLACE
        """)
        blocks = parse_search_replace_blocks(content)
        assert len(blocks) == 2
        assert blocks[0].file_path == "src/Foo.java"
        assert blocks[1].file_path == "src/Bar.java"

    def test_empty_search_section(self) -> None:
        """Empty SEARCH = file-creation block."""
        content = textwrap.dedent("""\
            src/New.java
            <<<<<<< SEARCH
            =======
            public class New {}
            >>>>>>> REPLACE
        """)
        blocks = parse_search_replace_blocks(content)
        assert len(blocks) == 1
        assert blocks[0].search == ""
        assert "public class New" in blocks[0].replace

    def test_multiline_blocks(self) -> None:
        content = textwrap.dedent("""\
            src/Foo.java
            <<<<<<< SEARCH
            line one
            line two
            line three
            =======
            replacement one
            replacement two
            >>>>>>> REPLACE
        """)
        blocks = parse_search_replace_blocks(content)
        assert blocks[0].search == "line one\nline two\nline three"
        assert blocks[0].replace == "replacement one\nreplacement two"

    def test_no_blocks_returns_empty_list(self) -> None:
        blocks = parse_search_replace_blocks("no markers here at all")
        assert blocks == []

    def test_missing_file_path_skips_block(self) -> None:
        # SEARCH marker with no path line before it
        content = textwrap.dedent("""\
            <<<<<<< SEARCH
            something
            =======
            else
            >>>>>>> REPLACE
        """)
        blocks = parse_search_replace_blocks(content)
        assert blocks == []

    def test_blank_line_between_path_and_marker(self) -> None:
        """A single blank line between the path and SEARCH marker is acceptable."""
        content = textwrap.dedent("""\
            src/Foo.java

            <<<<<<< SEARCH
            old
            =======
            new
            >>>>>>> REPLACE
        """)
        blocks = parse_search_replace_blocks(content)
        assert len(blocks) == 1
        assert blocks[0].file_path == "src/Foo.java"

    def test_model_prose_ignored(self) -> None:
        """Prose around blocks is ignored; only blocks are parsed."""
        content = textwrap.dedent("""\
            Here is my plan:

            src/Foo.java
            <<<<<<< SEARCH
            old
            =======
            new
            >>>>>>> REPLACE

            That's the change!
        """)
        blocks = parse_search_replace_blocks(content)
        assert len(blocks) == 1

    def test_trim_single_leading_trailing_blank(self) -> None:
        """Models sometimes add a blank after SEARCH or before ======= ."""
        content = textwrap.dedent("""\
            src/Foo.java
            <<<<<<< SEARCH

            old line

            =======

            new line

            >>>>>>> REPLACE
        """)
        blocks = parse_search_replace_blocks(content)
        assert blocks[0].search == "old line"
        assert blocks[0].replace == "new line"

    def test_fence_immediately_above_search_marker_does_not_drop_block(self) -> None:
        """A per-block ```lang fence between the file path and SEARCH marker
        must not cause the file path to be missed (models often fence each
        block despite "no Markdown fences" instructions)."""
        content = textwrap.dedent("""\
            src/Foo.java
            ```java
            <<<<<<< SEARCH
            old line
            =======
            new line
            >>>>>>> REPLACE
            ```
        """)
        blocks = parse_search_replace_blocks(content)
        assert len(blocks) == 1
        assert blocks[0].file_path == "src/Foo.java"
        assert blocks[0].search == "old line"
        assert blocks[0].replace == "new line"

    def test_whole_response_wrapped_in_single_outer_fence(self) -> None:
        """The entire response wrapped in one fence (path inside the fence,
        directly above SEARCH) must still parse instead of returning zero
        blocks."""
        content = "```\n" + textwrap.dedent("""\
            src/Foo.java
            <<<<<<< SEARCH
            old line
            =======
            new line
            >>>>>>> REPLACE
        """) + "```"
        blocks = parse_search_replace_blocks(content)
        assert len(blocks) == 1
        assert blocks[0].file_path == "src/Foo.java"
        assert blocks[0].search == "old line"
        assert blocks[0].replace == "new line"

    def test_multiple_blocks_inside_outer_fence(self) -> None:
        content = "```text\n" + textwrap.dedent("""\
            src/Foo.java
            <<<<<<< SEARCH
            alpha
            =======
            ALPHA
            >>>>>>> REPLACE

            src/Bar.java
            <<<<<<< SEARCH
            beta
            =======
            BETA
            >>>>>>> REPLACE
        """) + "```"
        blocks = parse_search_replace_blocks(content)
        assert len(blocks) == 2
        assert blocks[0].file_path == "src/Foo.java"
        assert blocks[1].file_path == "src/Bar.java"


# ---------------------------------------------------------------------------
# Applier tests
# ---------------------------------------------------------------------------


def test_apply_blocks_reports_structured_not_found_detail(tmp_path: Path) -> None:
    target = tmp_path / "src" / "Foo.java"
    target.parent.mkdir(parents=True)
    target.write_text("class Foo {\n    void run() {}\n}\n", encoding="utf-8")

    result = apply_blocks(
        tmp_path,
        [
            SearchReplaceBlock(
                file_path="src/Foo.java",
                search="void missing() {}",
                replace="void missing() { return; }",
            )
        ],
    )

    assert result.valid is False
    assert len(result.failure_details) == 1
    detail = result.failure_details[0]
    assert detail.file_path == "src/Foo.java"
    assert detail.error_type == "not_found"
    assert "void missing" in detail.search_preview
    assert "class Foo" in (detail.nearest_match_excerpt or "")


def test_apply_blocks_reports_ambiguous_match_count(tmp_path: Path) -> None:
    target = tmp_path / "src" / "Foo.java"
    target.parent.mkdir(parents=True)
    target.write_text("same\nsame\n", encoding="utf-8")

    result = apply_blocks(
        tmp_path,
        [SearchReplaceBlock(file_path="src/Foo.java", search="same", replace="other")],
    )

    assert result.valid is False
    assert result.failure_details[0].error_type == "ambiguous"
    assert result.failure_details[0].match_count == 2


class TestApplyBlocks:
    def test_single_block_exact_match(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "Foo.java"
        f.parent.mkdir()
        f.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

        blocks = [SearchReplaceBlock(file_path="src/Foo.java", search="beta", replace="BETA")]
        result = apply_blocks(tmp_path, blocks)

        assert result.valid
        assert result.patch_content is not None
        assert "BETA" in result.patch_content
        assert result.applications[0].applied

    def test_multi_line_block(self, tmp_path: Path) -> None:
        original = "def foo():\n    pass\n\ndef bar():\n    pass\n"
        f = tmp_path / "a.py"
        f.write_text(original, encoding="utf-8")

        blocks = [
            SearchReplaceBlock(
                file_path="a.py",
                search="def foo():\n    pass",
                replace="def foo():\n    return 42",
            )
        ]
        result = apply_blocks(tmp_path, blocks)

        assert result.valid
        assert "+    return 42" in result.patch_content  # type: ignore[operator]

    def test_not_found_returns_invalid(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text("nothing relevant\n", encoding="utf-8")

        blocks = [SearchReplaceBlock(file_path="a.py", search="missing text", replace="x")]
        result = apply_blocks(tmp_path, blocks)

        assert not result.valid
        assert result.patch_content is None
        assert any("not found" in e.lower() for e in result.errors)
        assert not result.applications[0].applied

    def test_ambiguous_returns_invalid(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text("x = 1\nx = 1\n", encoding="utf-8")

        blocks = [SearchReplaceBlock(file_path="a.py", search="x = 1", replace="x = 2")]
        result = apply_blocks(tmp_path, blocks)

        assert not result.valid
        assert any(
            "2 locations" in e or "ambiguous" in e.lower() or "matches" in e
            for e in result.errors
        )

    def test_file_missing_returns_invalid(self, tmp_path: Path) -> None:
        blocks = [SearchReplaceBlock(file_path="does/not/exist.py", search="x", replace="y")]
        result = apply_blocks(tmp_path, blocks)

        assert not result.valid
        assert any("not found" in e.lower() for e in result.errors)

    def test_multiple_blocks_same_file_compose(self, tmp_path: Path) -> None:
        """Blocks applied in order; second SEARCH matches modified content."""
        f = tmp_path / "a.py"
        f.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

        blocks = [
            SearchReplaceBlock(file_path="a.py", search="alpha", replace="ALPHA"),
            SearchReplaceBlock(file_path="a.py", search="ALPHA\nbeta", replace="ALPHA\nBETA"),
        ]
        result = apply_blocks(tmp_path, blocks)
        assert result.valid
        assert result.patch_content is not None

    def test_crlf_normalisation(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")

        blocks = [SearchReplaceBlock(file_path="a.py", search="alpha\nbeta", replace="merged")]
        result = apply_blocks(tmp_path, blocks)
        assert result.valid

    def test_no_blocks_returns_invalid(self, tmp_path: Path) -> None:
        result = apply_blocks(tmp_path, [])
        assert not result.valid
        assert any("no search" in e.lower() for e in result.errors)

    def test_no_change_returns_invalid(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text("alpha\n", encoding="utf-8")

        # SEARCH == REPLACE means no change
        blocks = [SearchReplaceBlock(file_path="a.py", search="alpha", replace="alpha")]
        result = apply_blocks(tmp_path, blocks)
        assert not result.valid
        assert any("no file content changed" in e.lower() for e in result.errors)

    def test_new_file_creation(self, tmp_path: Path) -> None:
        """Empty SEARCH = new file creation."""
        blocks = [SearchReplaceBlock(file_path="src/New.java", search="", replace="class New {}")]
        result = apply_blocks(tmp_path, blocks)
        assert result.valid
        assert result.patch_content is not None
        assert "new file" in result.patch_content

    def test_multi_file_both_succeed(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("old_a\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("old_b\n", encoding="utf-8")

        blocks = [
            SearchReplaceBlock(file_path="a.py", search="old_a", replace="new_a"),
            SearchReplaceBlock(file_path="b.py", search="old_b", replace="new_b"),
        ]
        result = apply_blocks(tmp_path, blocks)
        assert result.valid
        # Both files should appear in the diff
        assert "a.py" in result.patch_content  # type: ignore[operator]
        assert "b.py" in result.patch_content  # type: ignore[operator]

    def test_multi_file_one_fails(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("old_a\n", encoding="utf-8")
        # b.py does not exist

        blocks = [
            SearchReplaceBlock(file_path="a.py", search="old_a", replace="new_a"),
            SearchReplaceBlock(file_path="b.py", search="old_b", replace="new_b"),
        ]
        result = apply_blocks(tmp_path, blocks)
        assert not result.valid
        assert result.patch_content is None

    def test_diff_has_git_header(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text("hello\n", encoding="utf-8")
        blocks = [SearchReplaceBlock(file_path="a.py", search="hello", replace="world")]
        result = apply_blocks(tmp_path, blocks)
        assert result.patch_content is not None
        assert result.patch_content.startswith("diff --git a/a.py b/a.py")

    def test_to_dict_is_serialisable(self, tmp_path: Path) -> None:
        import json

        f = tmp_path / "a.py"
        f.write_text("hello\n", encoding="utf-8")
        blocks = [SearchReplaceBlock(file_path="a.py", search="hello", replace="world")]
        result = apply_blocks(tmp_path, blocks)
        d = result.to_dict()
        # Must be JSON-serialisable (no Path objects, etc.)
        json.dumps(d)
        assert d["valid"] is True


# ---------------------------------------------------------------------------
# Search-replace prompt tests
# ---------------------------------------------------------------------------


@_requires_py311
class TestSearchReplacePrompts:
    def _make_bundle(self) -> object:
        """Build a minimal ContextBundle-like stub."""
        from datetime import UTC, datetime

        from forge.context.bundle import ContextBundle, ContextBundleFile

        bf = ContextBundleFile(
            path="src/Foo.java",
            category="source",
            score=1,
            line_count=5,
            char_count=60,
            token_estimate=15,
            symbols=["Foo"],
            excerpts=["public class Foo {", "    void m() {}", "}"],
        )
        return ContextBundle(
            workset_name="test",
            query="test query",
            root="/repo",
            generated_at=datetime.now(tz=UTC),
            files=[bf],
        )

    def _make_plan(self) -> object:
        from datetime import UTC, datetime

        from forge.planning.planner import ImplementationPlan

        return ImplementationPlan(
            task="test task",
            workset_name="test",
            model="gpt-4",
            generated_at=datetime.now(tz=UTC),
            content="Make the change.",
        )

    def test_prompt_contains_srp_format(self) -> None:
        from forge.execution.execution_prompt import build_search_replace_prompt

        bundle = self._make_bundle()
        plan = self._make_plan()
        prompt, _ = build_search_replace_prompt("fix X", bundle, plan, "gpt-4")  # type: ignore[arg-type]
        assert "<<<<<<< SEARCH" in prompt
        assert "=======" in prompt
        assert ">>>>>>> REPLACE" in prompt

    def test_prompt_contains_task(self) -> None:
        from forge.execution.execution_prompt import build_search_replace_prompt

        bundle = self._make_bundle()
        plan = self._make_plan()
        prompt, _ = build_search_replace_prompt("very unique task XYZ", bundle, plan, "gpt-4")  # type: ignore[arg-type]
        assert "very unique task XYZ" in prompt

    def test_repair_prompt_includes_failures(self) -> None:
        from forge.execution.execution_prompt import build_search_replace_repair_prompt

        prompt = build_search_replace_repair_prompt(
            task="fix Y",
            original_response="<<<<<<< SEARCH\nbad\n=======\ngood\n>>>>>>> REPLACE",
            failures=["src/Foo.java: SEARCH content not found in file."],
            file_details="### src/Foo.java\n```\nactual content\n```",
        )
        assert "SEARCH content not found" in prompt
        assert "fix Y" in prompt

    def test_repair_prompt_includes_authoritative_excerpts(self) -> None:
        from forge.execution.execution_prompt import build_search_replace_repair_prompt

        prompt = build_search_replace_repair_prompt(
            task="fix Y",
            original_response="",
            failures=["src/Foo.java: SEARCH content not found in file."],
            file_details="",
            authoritative_excerpts="### src/Foo.java\n```\n1   | actual line\n```",
        )
        assert "Authoritative File Content" in prompt
        assert "actual line" in prompt


# ---------------------------------------------------------------------------
# End-to-end integration: parse → apply → diff is git-apply-able
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_parse_and_apply_produces_valid_diff(self, tmp_path: Path) -> None:
        """Parse model output then apply it and check the resulting diff is valid."""
        f = tmp_path / "src" / "Greeter.java"
        f.parent.mkdir()
        f.write_text(
            "public class Greeter {\n"
            "    public String greet() {\n"
            '        return "hello";\n'
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        model_output = textwrap.dedent("""\
            src/Greeter.java
            <<<<<<< SEARCH
                    return "hello";
            =======
                    return "hello, world";
            >>>>>>> REPLACE
        """)

        blocks = parse_search_replace_blocks(model_output)
        assert len(blocks) == 1
        result = apply_blocks(tmp_path, blocks)
        assert result.valid
        assert result.patch_content is not None
        assert "hello, world" in result.patch_content
        assert result.patch_content.startswith("diff --git")
