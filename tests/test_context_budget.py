"""Tests for implementation prompt target isolation (workset != editable files)."""

from __future__ import annotations

from datetime import UTC, datetime

from forge.context.bundle import ContextBundle, ContextBundleFile
from forge.edit_targets.models import EditableTarget, EditableTargetSet
from forge.execution.context_budget import (
    ImplementationPromptContext,
    build_target_isolated_bundle,
)


def _file(path: str, *, score: int = 50, category: str = "source") -> ContextBundleFile:
    return ContextBundleFile(
        path=path,
        category=category,
        score=score,
        line_count=10,
        char_count=200,
        token_estimate=50,
        symbols=[path.rsplit("/", 1)[-1].split(".")[0]],
        excerpts=[f"line {i}" for i in range(1, 11)],
    )


def _bundle(files: list[ContextBundleFile]) -> ContextBundle:
    return ContextBundle(
        workset_name="ws",
        query="q",
        root="/repo",
        generated_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        files=files,
    )


def test_approved_targets_become_editable_files() -> None:
    bundle = _bundle(
        [
            _file("archon-api/src/test/Foo.java"),
            _file("archon-api/src/main/Foo.java"),
        ]
    )
    targets = EditableTargetSet(
        task="fix Foo",
        workset_name="ws",
        targets=[
            EditableTarget(
                path="archon-api/src/test/Foo.java",
                reason="exact identifier match",
                confidence="primary",
                required=True,
            ),
            EditableTarget(
                path="archon-api/src/main/Foo.java",
                reason="related implementation target",
                confidence="related",
            ),
        ],
    )

    result = build_target_isolated_bundle("fix Foo", bundle, targets)

    assert isinstance(result, ImplementationPromptContext)
    assert {f.path for f in result.editable_files} == {
        "archon-api/src/test/Foo.java",
        "archon-api/src/main/Foo.java",
    }
    assert result.context_files == []
    assert result.omitted_files == []
    assert result.approved_paths == {
        "archon-api/src/test/Foo.java",
        "archon-api/src/main/Foo.java",
    }


def test_same_module_non_approved_files_become_context_only() -> None:
    bundle = _bundle(
        [
            _file("archon-api/src/test/Foo.java"),
            _file("archon-api/src/main/dto/FooDto.java"),
        ]
    )
    targets = EditableTargetSet(
        task="fix Foo",
        workset_name="ws",
        targets=[
            EditableTarget(
                path="archon-api/src/test/Foo.java",
                reason="exact identifier match",
                confidence="primary",
                required=True,
            ),
        ],
    )

    result = build_target_isolated_bundle("fix Foo", bundle, targets)

    assert [f.path for f in result.editable_files] == ["archon-api/src/test/Foo.java"]
    assert [f.path for f in result.context_files] == ["archon-api/src/main/dto/FooDto.java"]
    assert result.omitted_files == []


def test_cross_module_files_are_omitted() -> None:
    bundle = _bundle(
        [
            _file("archon-api/src/test/Foo.java"),
            _file("lens-api/src/main/Bar.java"),
        ]
    )
    targets = EditableTargetSet(
        task="fix Foo",
        workset_name="ws",
        targets=[
            EditableTarget(
                path="archon-api/src/test/Foo.java",
                reason="exact identifier match",
                confidence="primary",
                required=True,
            ),
        ],
    )

    result = build_target_isolated_bundle("fix Foo", bundle, targets)

    assert [f.path for f in result.editable_files] == ["archon-api/src/test/Foo.java"]
    assert result.context_files == []
    assert [f.path for f in result.omitted_files] == ["lens-api/src/main/Bar.java"]


def test_root_level_files_are_never_treated_as_cross_module() -> None:
    """A top-level file (e.g. README.md) has no module of its own, so it is
    never classified as cross-module/omitted purely for lacking a directory."""
    bundle = _bundle(
        [
            _file("archon-api/src/test/Foo.java"),
            _file("README.md", category="docs"),
        ]
    )
    targets = EditableTargetSet(
        task="fix Foo",
        workset_name="ws",
        targets=[
            EditableTarget(
                path="archon-api/src/test/Foo.java",
                reason="exact identifier match",
                confidence="primary",
                required=True,
            ),
        ],
    )

    result = build_target_isolated_bundle("fix Foo", bundle, targets)

    assert [f.path for f in result.context_files] == ["README.md"]
    assert result.omitted_files == []


def test_no_module_roots_means_nothing_is_omitted() -> None:
    """When approved targets have no module root (flat repo, or an
    allowed_context task with no strong identifier), nothing is cross-module."""
    bundle = _bundle(
        [
            _file("foo.py"),
            _file("bar.py"),
        ]
    )
    targets = EditableTargetSet(
        task="add caching",
        workset_name="ws",
        targets=[
            EditableTarget(
                path="foo.py",
                reason="allowed workset file",
                confidence="allowed_context",
            ),
        ],
    )

    result = build_target_isolated_bundle("add caching", bundle, targets)

    assert [f.path for f in result.editable_files] == ["foo.py"]
    assert [f.path for f in result.context_files] == ["bar.py"]
    assert result.omitted_files == []


def test_large_editable_file_budget_is_not_stolen_by_non_editable_files() -> None:
    """Budgeting for editable content runs over the editable subset only, so a
    highly-scored non-editable file can never consume the full-content budget
    an approved editable target needs."""
    big_editable = ContextBundleFile(
        path="archon-api/src/test/Foo.java",
        category="test",
        score=50,
        line_count=500,
        char_count=20_000,
        token_estimate=5000,
        symbols=["Foo"],
        excerpts=[f"line {i}" for i in range(1, 401)],
    )
    noisy_context = ContextBundleFile(
        path="archon-api/src/main/dto/FooDto.java",
        category="source",
        score=999,
        line_count=5,
        char_count=100,
        token_estimate=25,
        symbols=["FooDto"],
        excerpts=["class FooDto {}"],
    )
    bundle = _bundle([big_editable, noisy_context])
    targets = EditableTargetSet(
        task="fix Foo",
        workset_name="ws",
        targets=[
            EditableTarget(
                path="archon-api/src/test/Foo.java",
                reason="exact identifier match",
                confidence="primary",
                required=True,
            ),
        ],
    )

    result = build_target_isolated_bundle("fix Foo", bundle, targets)

    editable = result.editable_files[0]
    assert editable.path == "archon-api/src/test/Foo.java"
    # Gets real content (full or focused-excerpt), not starved to nothing by
    # the higher-scored non-editable file that never enters this budget pass.
    assert editable.lines


def test_to_dict_reports_path_lists() -> None:
    bundle = _bundle(
        [
            _file("archon-api/src/test/Foo.java"),
            _file("archon-api/src/main/dto/FooDto.java"),
            _file("lens-api/src/main/Bar.java"),
        ]
    )
    targets = EditableTargetSet(
        task="fix Foo",
        workset_name="ws",
        targets=[
            EditableTarget(
                path="archon-api/src/test/Foo.java",
                reason="exact identifier match",
                confidence="primary",
                required=True,
            ),
        ],
    )

    result = build_target_isolated_bundle("fix Foo", bundle, targets).to_dict()

    assert result["editable_context_files"] == ["archon-api/src/test/Foo.java"]
    assert result["context_only_files"] == ["archon-api/src/main/dto/FooDto.java"]
    assert result["omitted_files"] == ["lens-api/src/main/Bar.java"]
    assert result["approved_paths"] == ["archon-api/src/test/Foo.java"]
