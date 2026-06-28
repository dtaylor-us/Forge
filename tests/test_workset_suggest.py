"""Tests for workset candidate selection (Phase 2B)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from forge.cli.app import app
from forge.worksets.candidate import WorksetSuggestion
from forge.worksets.scoring import (
    file_category,
    is_test_query,
    score_candidate,
    tokenize_query,
)
from forge.worksets.suggest import suggest_candidates

runner = CliRunner()


# ---------------------------------------------------------------------------
# tokenize_query
# ---------------------------------------------------------------------------


def test_tokenize_basic():
    tokens = tokenize_query("model manager config")
    assert tokens == ["model", "manager", "config"]


def test_tokenize_removes_stop_words():
    tokens = tokenize_query("the model for a config")
    assert "the" not in tokens
    assert "for" not in tokens
    assert "model" in tokens
    assert "config" in tokens


def test_tokenize_short_tokens_removed():
    tokens = tokenize_query("a b cd model")
    assert "a" not in tokens
    assert "b" not in tokens
    assert "cd" in tokens
    assert "model" in tokens


def test_tokenize_empty():
    assert tokenize_query("") == []


def test_tokenize_lowercases():
    tokens = tokenize_query("Model Manager CONFIG")
    assert tokens == ["model", "manager", "config"]


# ---------------------------------------------------------------------------
# is_test_query
# ---------------------------------------------------------------------------


def test_is_test_query_positive():
    assert is_test_query(["timeout", "tests", "regression"])
    assert is_test_query(["test", "config"])
    assert is_test_query(["fixture"])


def test_is_test_query_negative():
    assert not is_test_query(["model", "manager", "config"])
    assert not is_test_query([])


# ---------------------------------------------------------------------------
# file_category
# ---------------------------------------------------------------------------


def test_file_category_source():
    assert file_category(Path("forge/models/manager.py")) == "source"


def test_file_category_test():
    assert file_category(Path("tests/test_model_manager.py")) == "test"


def test_file_category_config():
    assert file_category(Path("pyproject.toml")) == "config"


def test_file_category_doc():
    assert file_category(Path("docs/development/DEVELOPMENT_LOG.md")) == "doc"


# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------


def test_score_filename_token_match():
    candidate = score_candidate(Path("forge/models/manager.py"), ["manager"])
    assert candidate.score > 0
    assert any("manager" in r.label for r in candidate.reasons)


def test_score_path_segment_match():
    candidate = score_candidate(Path("forge/models/manager.py"), ["models"])
    assert candidate.score > 0
    assert any("path matched" in r.label for r in candidate.reasons)


def test_score_content_match():
    lines = ["class ModelManager:\n", "    def config(self):\n"]
    candidate = score_candidate(Path("forge/models/manager.py"), ["config"], lines)
    assert any("content matched" in r.label for r in candidate.reasons)
    assert candidate.content_matches


def test_score_no_match_returns_type_bonus_only():
    candidate = score_candidate(Path("forge/models/manager.py"), ["zzznomatch"])
    # Only source file bonus remains
    assert candidate.score == 3  # SCORE_SOURCE_FILE
    assert any("source file" in r.label for r in candidate.reasons)


def test_score_important_file_bonus():
    candidate = score_candidate(Path("pyproject.toml"), ["model"])
    reason_labels = [r.label for r in candidate.reasons]
    assert any("important project file" in label for label in reason_labels)


def test_score_multiple_tokens():
    candidate = score_candidate(Path("forge/models/manager.py"), ["model", "manager"])
    assert candidate.score >= 10  # at least one filename match


# ---------------------------------------------------------------------------
# suggest_candidates
# ---------------------------------------------------------------------------


def test_suggest_returns_suggestion(tmp_path):
    (tmp_path / "forge").mkdir()
    (tmp_path / "forge" / "manager.py").write_text("class ModelManager:\n    pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_manager.py").write_text("def test_model():\n    pass\n")

    result = suggest_candidates("model manager", tmp_path)

    assert isinstance(result, WorksetSuggestion)
    assert result.query == "model manager"
    assert "model" in result.tokens
    assert "manager" in result.tokens


def test_suggest_excludes_tests_by_default(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "manager.py").write_text("class Manager: pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_manager.py").write_text("def test_manager(): pass\n")

    result = suggest_candidates("manager", tmp_path, include_tests=False)

    paths = [str(c.path) for c in result.candidates]
    assert not any("test_manager" in p for p in paths)
    assert any("manager" in p for p in paths)


def test_suggest_includes_tests_when_flag_set(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "manager.py").write_text("class Manager: pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_manager.py").write_text("def test_manager(): pass\n")

    result = suggest_candidates("manager", tmp_path, include_tests=True)

    paths = [str(c.path) for c in result.candidates]
    assert any("test_manager" in p for p in paths)


def test_suggest_includes_tests_for_test_query(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_manager.py").write_text("def test_manager(): pass\n")

    result = suggest_candidates("timeout tests manager", tmp_path)

    paths = [str(c.path) for c in result.candidates]
    assert any("test_manager" in p for p in paths)


def test_suggest_ranked_by_score(tmp_path):
    (tmp_path / "model_manager.py").write_text("class ModelManager: pass\n")
    (tmp_path / "other.py").write_text("print('hello')\n")

    result = suggest_candidates("model manager", tmp_path)

    if len(result.candidates) >= 2:
        assert result.candidates[0].score >= result.candidates[1].score


def test_suggest_max_results(tmp_path):
    for i in range(10):
        (tmp_path / f"model_{i}.py").write_text(f"# model file {i}\n")

    result = suggest_candidates("model", tmp_path, max_results=3)

    assert len(result.candidates) <= 3


def test_suggest_empty_query(tmp_path):
    (tmp_path / "model.py").write_text("class Model: pass\n")

    result = suggest_candidates("", tmp_path)

    assert result.candidates == []


def test_suggest_no_match(tmp_path):
    (tmp_path / "manager.py").write_text("class Manager: pass\n")

    result = suggest_candidates("zzznomatch", tmp_path)

    # manager.py will still score for source file bonus — candidates may be non-empty
    # but score should be low (just the type bonus)
    for c in result.candidates:
        assert c.score <= 5


# ---------------------------------------------------------------------------
# CLI: forge workset suggest
# ---------------------------------------------------------------------------


def test_cli_workset_suggest(tmp_path):
    (tmp_path / "forge").mkdir()
    (tmp_path / "forge" / "model_manager.py").write_text("class ModelManager: pass\n")

    result = runner.invoke(app, ["workset", "suggest", "model manager", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "model_manager" in result.output or "Workset Suggestion" in result.output


def test_cli_workset_suggest_include_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_model.py").write_text("def test_model(): pass\n")

    result = runner.invoke(
        app,
        ["workset", "suggest", "model", "--root", str(tmp_path), "--include-tests"],
    )

    assert result.exit_code == 0
    assert "test_model" in result.output


def test_cli_workset_suggest_json(tmp_path):
    (tmp_path / "manager.py").write_text("class Manager: pass\n")

    result = runner.invoke(
        app,
        ["workset", "suggest", "manager", "--root", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["query"] == "manager"
    assert "tokens" in data
    assert "candidates" in data
    for c in data["candidates"]:
        assert "path" in c
        assert "score" in c
        assert "file_category" in c
        assert "reasons" in c


def test_cli_workset_suggest_no_results(tmp_path):
    result = runner.invoke(
        app,
        ["workset", "suggest", "zzznomatchatall", "--root", str(tmp_path)],
    )

    assert result.exit_code == 0


def test_cli_workset_suggest_max_results(tmp_path):
    for i in range(10):
        (tmp_path / f"model_{i}.py").write_text(f"# model {i}\n")

    result = runner.invoke(
        app,
        ["workset", "suggest", "model", "--root", str(tmp_path), "--max-results", "3", "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["candidates"]) <= 3
