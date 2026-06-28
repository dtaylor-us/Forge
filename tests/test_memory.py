"""Tests for Epic 3.1: Engineering Memory subsystem."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from forge.cli.app import app
from forge.memory.manager import MemoryManager
from forge.memory.models import MemoryItem, MemoryType
from forge.memory.search import search_memory
from forge.memory.similarity import find_similar
from forge.memory.store import (
    MemoryStoreError,
    delete_item,
    list_items,
    load_index,
    load_item,
    rebuild_index,
    save_item,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(
    id: str = "abc12345",
    type: MemoryType = MemoryType.plan,
    title: str = "Implement OAuth",
    workset: str = "authentication",
    tags: list[str] | None = None,
    summary: str = "OAuth implementation plan",
    related_files: list[str] | None = None,
) -> MemoryItem:
    return MemoryItem(
        id=id,
        type=type,
        title=title,
        created_at="2026-06-28T00:00:00+00:00",
        repository="/repo",
        workset=workset,
        tags=tags or ["oauth", "authentication"],
        summary=summary,
        related_files=related_files or ["forge/models/manager.py"],
        related_plans=[],
        related_worksets=["authentication"],
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_memory_item_round_trip() -> None:
    item = _item()
    restored = MemoryItem.from_dict(item.to_dict())
    assert restored.id == item.id
    assert restored.type == item.type
    assert restored.title == item.title
    assert restored.tags == item.tags


def test_memory_item_to_dict_shape() -> None:
    item = _item()
    d = item.to_dict()
    assert d["type"] == "plan"
    assert "related_files" in d
    assert "related_plans" in d
    assert "related_worksets" in d


def test_memory_type_values() -> None:
    assert MemoryType.plan.value == "plan"
    assert MemoryType.bug.value == "bug"
    assert MemoryType.decision.value == "decision"
    assert MemoryType.adr.value == "adr"


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------


def test_save_and_load_item(tmp_path: Path) -> None:
    item = _item()
    save_item(tmp_path, item)
    loaded = load_item(tmp_path, item.id)
    assert loaded.id == item.id
    assert loaded.title == item.title


def test_save_creates_subdirs(tmp_path: Path) -> None:
    item = _item()
    save_item(tmp_path, item)
    assert (tmp_path / ".forge" / "memory" / "plans").is_dir()


def test_save_updates_index(tmp_path: Path) -> None:
    item = _item()
    save_item(tmp_path, item)
    index = load_index(tmp_path)
    assert any(e["id"] == item.id for e in index)


def test_load_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(MemoryStoreError):
        load_item(tmp_path, "nonexistent")


def test_list_items_empty(tmp_path: Path) -> None:
    assert list_items(tmp_path) == []


def test_list_items_multiple(tmp_path: Path) -> None:
    a = _item(id="aaa11111", title="Plan A")
    b = _item(id="bbb22222", title="Plan B", type=MemoryType.decision)
    save_item(tmp_path, a)
    save_item(tmp_path, b)
    items = list_items(tmp_path)
    ids = {i.id for i in items}
    assert "aaa11111" in ids
    assert "bbb22222" in ids


def test_delete_item(tmp_path: Path) -> None:
    item = _item()
    save_item(tmp_path, item)
    delete_item(tmp_path, item.id)
    with pytest.raises(MemoryStoreError):
        load_item(tmp_path, item.id)


def test_delete_removes_from_index(tmp_path: Path) -> None:
    item = _item()
    save_item(tmp_path, item)
    delete_item(tmp_path, item.id)
    index = load_index(tmp_path)
    assert not any(e["id"] == item.id for e in index)


def test_rebuild_index(tmp_path: Path) -> None:
    a = _item(id="aaa11111", title="Plan A")
    b = _item(id="bbb22222", title="Plan B")
    save_item(tmp_path, a)
    save_item(tmp_path, b)
    index_path = tmp_path / ".forge" / "memory" / "index.json"
    index_path.write_text('{"schema_version": 1, "items": []}', encoding="utf-8")
    count = rebuild_index(tmp_path)
    assert count == 2
    index = load_index(tmp_path)
    ids = {e["id"] for e in index}
    assert "aaa11111" in ids
    assert "bbb22222" in ids


def test_duplicate_save_overwrites(tmp_path: Path) -> None:
    item = _item(title="First")
    save_item(tmp_path, item)
    updated = _item(title="Updated")
    save_item(tmp_path, updated)
    loaded = load_item(tmp_path, item.id)
    assert loaded.title == "Updated"
    index = load_index(tmp_path)
    entries = [e for e in index if e["id"] == item.id]
    assert len(entries) == 1


def test_missing_memory_dir_list_returns_empty(tmp_path: Path) -> None:
    assert list_items(tmp_path) == []


# ---------------------------------------------------------------------------
# Manager tests
# ---------------------------------------------------------------------------


def test_manager_add_and_get(tmp_path: Path) -> None:
    mgr = MemoryManager(tmp_path)
    item = mgr.add(
        type=MemoryType.plan,
        title="Add login flow",
        workset="auth",
        tags=["auth", "login"],
        summary="Login implementation",
    )
    fetched = mgr.get(item.id)
    assert fetched.title == "Add login flow"
    assert fetched.tags == ["auth", "login"]


def test_manager_list_sorted_desc(tmp_path: Path) -> None:
    mgr = MemoryManager(tmp_path)
    mgr.add(type=MemoryType.plan, title="Old plan")
    mgr.add(type=MemoryType.decision, title="New decision")
    items = mgr.list()
    assert items[0].created_at >= items[-1].created_at


def test_manager_delete(tmp_path: Path) -> None:
    mgr = MemoryManager(tmp_path)
    item = mgr.add(type=MemoryType.bug, title="Auth bug")
    mgr.delete(item.id)
    with pytest.raises(MemoryStoreError):
        mgr.get(item.id)


def test_manager_rebuild(tmp_path: Path) -> None:
    mgr = MemoryManager(tmp_path)
    mgr.add(type=MemoryType.plan, title="Plan X")
    count = mgr.rebuild()
    assert count >= 1


def test_manager_get_missing_raises(tmp_path: Path) -> None:
    mgr = MemoryManager(tmp_path)
    with pytest.raises(MemoryStoreError):
        mgr.get("notexist")


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


def test_search_empty_memory(tmp_path: Path) -> None:
    results = search_memory(tmp_path, "oauth")
    assert results == []


def test_search_title_match(tmp_path: Path) -> None:
    save_item(tmp_path, _item(title="Implement OAuth flow"))
    results = search_memory(tmp_path, "oauth")
    assert len(results) == 1
    assert results[0].score > 0


def test_search_tag_match(tmp_path: Path) -> None:
    save_item(tmp_path, _item(title="Unrelated", tags=["oauth", "security"]))
    results = search_memory(tmp_path, "oauth")
    assert len(results) >= 1


def test_search_returns_reasons(tmp_path: Path) -> None:
    save_item(tmp_path, _item(title="OAuth integration"))
    results = search_memory(tmp_path, "oauth")
    assert results[0].reasons


def test_search_ranking_order(tmp_path: Path) -> None:
    save_item(tmp_path, _item(id="low111", title="Unrelated task", tags=[]))
    save_item(tmp_path, _item(id="high222", title="OAuth authentication plan", tags=["oauth"]))
    results = search_memory(tmp_path, "oauth authentication")
    assert results[0].item.id == "high222"


def test_search_max_results(tmp_path: Path) -> None:
    for i in range(5):
        save_item(tmp_path, _item(id=f"item{i}000", title=f"OAuth plan {i}"))
    results = search_memory(tmp_path, "oauth", max_results=3)
    assert len(results) <= 3


def test_search_no_match_returns_empty(tmp_path: Path) -> None:
    save_item(
        tmp_path,
        _item(
            title="Kubernetes deployment",
            tags=["k8s", "deployment"],
            summary="Kubernetes rollout",
        ),
    )
    results = search_memory(tmp_path, "oauth")
    assert results == []


def test_search_summary_match(tmp_path: Path) -> None:
    save_item(tmp_path, _item(title="Unrelated", summary="OAuth token refresh logic", tags=[]))
    results = search_memory(tmp_path, "oauth")
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# Similarity tests
# ---------------------------------------------------------------------------


def test_similarity_empty_memory(tmp_path: Path) -> None:
    results = find_similar(tmp_path, "oauth", workset="auth")
    assert results == []


def test_similarity_shared_files(tmp_path: Path) -> None:
    save_item(tmp_path, _item(related_files=["forge/auth/oauth.py", "forge/auth/tokens.py"]))
    results = find_similar(tmp_path, "login", related_files=["forge/auth/oauth.py"], workset="auth")
    assert len(results) >= 1
    assert results[0].score > 0


def test_similarity_shared_workset(tmp_path: Path) -> None:
    save_item(tmp_path, _item(workset="authentication"))
    results = find_similar(tmp_path, "entra id", workset="authentication")
    assert len(results) >= 1


def test_similarity_shared_tags(tmp_path: Path) -> None:
    save_item(tmp_path, _item(tags=["oauth", "security"]))
    results = find_similar(tmp_path, "entra", tags=["oauth", "security"])
    assert len(results) >= 1


def test_similarity_max_results(tmp_path: Path) -> None:
    for i in range(5):
        save_item(tmp_path, _item(id=f"sim{i}0000", title=f"Auth plan {i}", tags=["oauth"]))
    results = find_similar(tmp_path, "auth", tags=["oauth"], max_results=2)
    assert len(results) <= 2


def test_similarity_reasons_populated(tmp_path: Path) -> None:
    save_item(tmp_path, _item(related_files=["forge/auth/oauth.py"]))
    results = find_similar(tmp_path, "auth", related_files=["forge/auth/oauth.py"])
    assert results[0].reasons


# ---------------------------------------------------------------------------
# Repository isolation
# ---------------------------------------------------------------------------


def test_repository_isolation(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()
    item_a = _item(id="aaaaaa11", title="Repo A plan")
    item_b = _item(id="bbbbbb22", title="Repo B plan")
    save_item(repo_a, item_a)
    save_item(repo_b, item_b)
    items_a = list_items(repo_a)
    items_b = list_items(repo_b)
    assert all(i.id == "aaaaaa11" for i in items_a)
    assert all(i.id == "bbbbbb22" for i in items_b)


# ---------------------------------------------------------------------------
# Planning integration tests
# ---------------------------------------------------------------------------


def test_planning_searches_memory_before_generating(tmp_path: Path) -> None:
    """generate_plan should search memory and include results in the prompt."""
    from forge.context.bundle import ContextBundle
    from forge.models.types import ModelResponse
    from forge.planning.planner import generate_plan
    from forge.worksets.store import save as save_workset

    (tmp_path / ".git").mkdir()
    save_workset(
        tmp_path,
        {
            "name": "auth",
            "schema_version": 1,
            "query": "authentication",
            "created_at": "2026-06-28T00:00:00+00:00",
            "updated_at": "2026-06-28T00:00:00+00:00",
            "files": [],
        },
    )

    save_item(
        tmp_path,
        _item(
            id="prev1234",
            title="Implement OAuth authentication",
            workset="auth",
            tags=["oauth", "auth", "azure"],
        ),
    )

    mock_bundle = ContextBundle(
        workset_name="auth",
        query="authentication",
        root=str(tmp_path),
        generated_at="2026-06-28T00:00:00+00:00",
    )
    mock_response = ModelResponse(content="# Plan\n\nDone.", model="test-model", provider="test")
    mock_manager = MagicMock()
    mock_manager.config.return_value = MagicMock(default_model="test-model")
    mock_manager.ask.return_value = mock_response

    with patch("forge.planning.planner.generate_bundle", return_value=mock_bundle):
        generate_plan(
            tmp_path,
            "Add Azure OAuth authentication",
            "auth",
            model_manager=mock_manager,
            save_to_memory=False,
        )

    call_kwargs = mock_manager.ask.call_args[1]
    call_args = mock_manager.ask.call_args[0]
    prompt_sent = call_kwargs["prompt"] if call_kwargs else call_args[0]
    assert "prev1234" in prompt_sent or "Engineering Memory" in prompt_sent


def test_planning_saves_to_memory(tmp_path: Path) -> None:
    """generate_plan with save_to_memory=True should persist a plan item."""
    from forge.context.bundle import ContextBundle
    from forge.models.types import ModelResponse
    from forge.planning.planner import generate_plan
    from forge.worksets.store import save as save_workset

    (tmp_path / ".git").mkdir()
    save_workset(
        tmp_path,
        {
            "name": "auth",
            "schema_version": 1,
            "query": "authentication",
            "created_at": "2026-06-28T00:00:00+00:00",
            "updated_at": "2026-06-28T00:00:00+00:00",
            "files": [],
        },
    )

    mock_bundle = ContextBundle(
        workset_name="auth",
        query="authentication",
        root=str(tmp_path),
        generated_at="2026-06-28T00:00:00+00:00",
    )
    mock_response = ModelResponse(content="# Plan", model="test-model", provider="test")
    mock_manager = MagicMock()
    mock_manager.config.return_value = MagicMock(default_model="test-model")
    mock_manager.ask.return_value = mock_response

    with patch("forge.planning.planner.generate_bundle", return_value=mock_bundle):
        plan = generate_plan(
            tmp_path,
            "Add Azure Entra ID",
            "auth",
            model_manager=mock_manager,
            save_to_memory=True,
        )

    assert plan.memory_item_id is not None
    mgr = MemoryManager(tmp_path)
    item = mgr.get(plan.memory_item_id)
    assert item.type == MemoryType.plan
    assert item.workset == "auth"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def _make_memory_repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    save_item(tmp_path, _item(id="cli01234", title="OAuth plan", workset="auth", tags=["oauth"]))
    return tmp_path


def test_cli_memory_list(tmp_path: Path) -> None:
    _make_memory_repo(tmp_path)
    result = runner.invoke(app, ["memory", "list", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "OAuth plan" in result.output


def test_cli_memory_list_empty(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = runner.invoke(app, ["memory", "list", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "No memory" in result.output


def test_cli_memory_list_json(tmp_path: Path) -> None:
    _make_memory_repo(tmp_path)
    result = runner.invoke(app, ["memory", "list", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["title"] == "OAuth plan"


def test_cli_memory_show(tmp_path: Path) -> None:
    _make_memory_repo(tmp_path)
    result = runner.invoke(app, ["memory", "show", "cli01234", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "OAuth plan" in result.output


def test_cli_memory_show_missing(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = runner.invoke(app, ["memory", "show", "notexist", "--root", str(tmp_path)])
    assert result.exit_code == 1


def test_cli_memory_show_json(tmp_path: Path) -> None:
    _make_memory_repo(tmp_path)
    result = runner.invoke(app, ["memory", "show", "cli01234", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "cli01234"


def test_cli_memory_search(tmp_path: Path) -> None:
    _make_memory_repo(tmp_path)
    result = runner.invoke(app, ["memory", "search", "oauth", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "OAuth" in result.output


def test_cli_memory_search_no_match(tmp_path: Path) -> None:
    _make_memory_repo(tmp_path)
    result = runner.invoke(app, ["memory", "search", "kubernetes", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "No matching" in result.output


def test_cli_memory_search_json(tmp_path: Path) -> None:
    _make_memory_repo(tmp_path)
    result = runner.invoke(app, ["memory", "search", "oauth", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["item"]["id"] == "cli01234"


def test_cli_memory_related(tmp_path: Path) -> None:
    _make_memory_repo(tmp_path)
    result = runner.invoke(
        app, ["memory", "related", "authentication", "--workset", "auth", "--root", str(tmp_path)]
    )
    assert result.exit_code == 0


def test_cli_memory_rebuild(tmp_path: Path) -> None:
    _make_memory_repo(tmp_path)
    result = runner.invoke(app, ["memory", "rebuild", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "rebuilt" in result.output.lower()


def test_cli_memory_rebuild_empty(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = runner.invoke(app, ["memory", "rebuild", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "0" in result.output
