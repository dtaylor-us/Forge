"""Tests for workset candidate selection (Phase 2B)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from forge.cli.app import app
from forge.repository.files import list_relevant_files
from forge.worksets.candidate import WorksetSuggestion
from forge.worksets.query import parse_query
from forge.worksets.scoring import (
    SCORE_FILENAME_TERM,
    _matched_terms,
    _term_points,
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
    assert candidate.confidence == 0
    assert candidate.importance > 0
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


def test_suggest_identifier_finds_related_implementation_from_test_name(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "PaymentController.py").write_text("class PaymentController: pass\n")
    (tmp_path / "src" / "PaymentService.py").write_text("class PaymentService: pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "PaymentControllerTest.py").write_text(
        "class PaymentControllerTest: pass\n"
    )

    result = suggest_candidates("fix PaymentControllerTest", tmp_path)
    paths = [c.path.as_posix() for c in result.candidates]

    assert paths.index("src/PaymentController.py") < paths.index("tests/PaymentControllerTest.py")
    assert "src/PaymentService.py" in paths
    assert "tests/PaymentControllerTest.py" in paths


def test_bugfix_query_includes_tests_by_default(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "SessionController.py").write_text("class SessionController: pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "SessionControllerTest.py").write_text(
        "class SessionControllerTest: pass\n"
    )

    result = suggest_candidates("fix SessionController", tmp_path, include_tests=False)

    assert any(c.path.as_posix() == "tests/SessionControllerTest.py" for c in result.candidates)


def test_infrastructure_quota_keeps_source_files_from_being_displaced(tmp_path):
    (tmp_path / "src").mkdir()
    for name in ["PaymentController", "PaymentService", "PaymentRepository", "PaymentMapper"]:
        (tmp_path / "src" / f"{name}.py").write_text(f"class {name}: pass\n")
    for name in ["Dockerfile", "README.md", "pyproject.toml", "package.json"]:
        (tmp_path / name).write_text("payment configuration\n")

    result = suggest_candidates("fix PaymentController", tmp_path, max_results=7)
    paths = [c.path.as_posix() for c in result.candidates]
    infra = [p for p in paths if p in {"Dockerfile", "README.md", "pyproject.toml", "package.json"}]

    assert paths[0] == "src/PaymentController.py"
    assert "src/PaymentService.py" in paths
    assert len(infra) <= 3


def test_generated_frontend_caches_are_ignored(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("class App: pass\n")
    for directory in [
        ".vite",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".cache",
        ".parcel-cache",
        "coverage",
        "out",
    ]:
        cache = tmp_path / directory
        cache.mkdir()
        (cache / "app.py").write_text("class CachedApp: pass\n")

    paths = [path.as_posix() for path in list_relevant_files(tmp_path, max_results=50)]

    assert "src/app.py" in paths
    assert not any(path.startswith(".vite/") for path in paths)
    assert not any(path.startswith(".next/") for path in paths)
    assert not any(path.startswith("coverage/") for path in paths)


def test_candidate_reasons_are_deterministic_and_not_duplicated(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "SessionController.py").write_text("class SessionController: pass\n")

    result = suggest_candidates("fix SessionController", tmp_path)
    candidate = result.candidates[0]
    labels = [reason.label for reason in candidate.reasons]

    assert labels == list(dict.fromkeys(labels))
    assert any(label.startswith("Primary Match:") for label in labels)
    assert any(label.startswith("Identifier Match:") for label in labels)


def test_suggest_empty_query(tmp_path):
    (tmp_path / "model.py").write_text("class Model: pass\n")

    result = suggest_candidates("", tmp_path)

    assert result.candidates == []


def test_suggest_no_match(tmp_path):
    (tmp_path / "manager.py").write_text("class Manager: pass\n")

    result = suggest_candidates("zzznomatch", tmp_path)

    assert result.candidates == []


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


# ---------------------------------------------------------------------------
# Regression: large monorepo workset selection (the SessionControllerIntegrationTest bug)
#
# A deterministic-but-truncated file listing combined with unweighted generic
# search terms ("session", "test", "api" decomposed from the identifier) used
# to let an unrelated file in a large, mixed-language monorepo outrank the
# real target. These tests pin both fixes: the file enumeration must not
# truncate before scoring (Root Cause A), and decomposed generic identifier
# parts must not score as strongly as the full, distinctive identifier
# (Root Cause B).
# ---------------------------------------------------------------------------


def test_suggest_finds_target_file_among_many_decoys_across_directories(tmp_path):
    # Simulate a large monorepo: hundreds of unrelated files spread across many
    # directories in a different "service" than the real target, so the target
    # would be enumerated past any naive fixed-size file listing cap.
    decoys_dir = tmp_path / "axiom-ui" / "src"
    for i in range(300):
        sub = decoys_dir / f"module_{i}"
        sub.mkdir(parents=True)
        (sub / f"Unrelated{i}.ts").write_text(f"export function unrelated{i}() {{}}\n")

    target_dir = tmp_path / "archon-api" / "src" / "test" / "java" / "com" / "archon" / "api"
    target_dir.mkdir(parents=True)
    (target_dir / "SessionControllerIntegrationTest.java").write_text(
        "public class SessionControllerIntegrationTest {}\n"
    )

    result = suggest_candidates(
        "fix SessionControllerIntegrationTest", tmp_path, include_tests=True
    )
    paths = [c.path.as_posix() for c in result.candidates]

    assert paths, "expected at least one candidate"
    assert paths[0].endswith("SessionControllerIntegrationTest.java")
    assert not any(p.startswith("axiom-ui/") for p in paths)


def test_suggest_does_not_rank_generic_substring_decoys_above_real_target(tmp_path):
    # Files whose names/content merely contain a generic decomposed-identifier
    # part as a raw substring ("test" inside "Latest"/"Contest") must not be
    # treated as a match: matching must be token/boundary-aware for short,
    # generic terms rather than a coincidental substring hit.
    decoys_dir = tmp_path / "other"
    decoys_dir.mkdir()
    (decoys_dir / "Latest.py").write_text("class Latest:\n    pass\n")
    (decoys_dir / "Contest.py").write_text("class Contest:\n    pass\n")

    target_dir = tmp_path / "src"
    target_dir.mkdir()
    (target_dir / "SessionController.py").write_text("class SessionController:\n    pass\n")

    result = suggest_candidates("fix SessionControllerTest", tmp_path, include_tests=True)
    paths = [c.path.as_posix() for c in result.candidates]

    assert paths
    assert paths[0] == "src/SessionController.py"
    assert "other/Latest.py" not in paths
    assert "other/Contest.py" not in paths


def test_suggest_ignores_generic_identifier_part_controller_decoys(tmp_path):
    decoys_dir = tmp_path / "lens-api" / "src" / "main" / "java" / "com" / "lens" / "api"
    decoys_dir.mkdir(parents=True)
    for name in ["EvidenceController", "GapController", "GovernanceController"]:
        (decoys_dir / f"{name}.java").write_text(f"public class {name} {{}}\n")

    result = suggest_candidates(
        "fix SessionControllerIntegrationTest", tmp_path, include_tests=True
    )
    paths = [c.path.as_posix() for c in result.candidates]

    assert not paths


def test_score_full_identifier_outweighs_decomposed_part():
    full_identifier_query = parse_query("fix SessionControllerIntegrationTest")
    candidate = score_candidate(
        Path("archon-api/src/test/java/com/archon/api/SessionControllerIntegrationTest.java"),
        full_identifier_query,
    )
    decoy_query = parse_query("fix SessionControllerIntegrationTest")
    decoy_candidate = score_candidate(Path("other/latest.ts"), decoy_query)

    assert candidate.score > decoy_candidate.score


def test_filename_term_weight_scales_with_term_specificity():
    from forge.worksets.query import SearchTerm

    full_term = SearchTerm(value="SessionControllerTest", weight=5, kind="identifier")
    part_term = SearchTerm(value="session", weight=1, kind="identifier_part")

    name_lower = "sessioncontrollertest.py"
    stem_normalized = "sessioncontrollertest"
    stem_parts = {"session", "controller", "test"}
    matched_full = _matched_terms(name_lower, stem_normalized, stem_parts, [full_term])
    matched_part = _matched_terms(name_lower, stem_normalized, stem_parts, [part_term])

    assert _term_points(SCORE_FILENAME_TERM, matched_full[0]) > _term_points(
        SCORE_FILENAME_TERM, matched_part[0]
    )


def test_generic_identifier_part_does_not_match_filename_boundary():
    from forge.worksets.query import SearchTerm

    controller_part = SearchTerm(value="Controller", weight=1, kind="identifier_part")

    matched = _matched_terms(
        "evidencecontroller.java",
        "evidencecontroller",
        {"evidence", "controller"},
        [controller_part],
    )

    assert matched == []


def test_list_relevant_files_unbounded_includes_deeply_nested_file(tmp_path):
    # "aardvark-ui" deliberately sorts alphabetically before "archon-api" (both
    # share file-priority 0 via the "src" path segment), so with a fixed cap
    # these decoys would push the real target out of the truncated listing.
    decoys_dir = tmp_path / "aardvark-ui" / "src"
    for i in range(250):
        sub = decoys_dir / f"module_{i}"
        sub.mkdir(parents=True)
        (sub / f"Unrelated{i}.ts").write_text("export function unrelated() {}\n")

    target_dir = tmp_path / "archon-api" / "src" / "test" / "java"
    target_dir.mkdir(parents=True)
    (target_dir / "SessionControllerIntegrationTest.java").write_text("class X {}\n")

    bounded = list_relevant_files(tmp_path, max_results=200)
    unbounded = list_relevant_files(tmp_path, max_results=None)

    target = Path("archon-api/src/test/java/SessionControllerIntegrationTest.java")
    assert target not in bounded
    assert target in unbounded


# ---------------------------------------------------------------------------
# Regression: workflow template threading into query parsing
# ---------------------------------------------------------------------------


def test_create_workset_threads_workflow_into_intent(tmp_path):
    from forge.worksets.manager import create_workset

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Widget.py").write_text("class Widget:\n    pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "WidgetTest.py").write_text("class WidgetTest:\n    pass\n")

    # "update Widget" alone maps to the generic intent (not bugfix), so test
    # files would normally be excluded. An explicit bugfix workflow (as set by
    # the `forge workflow bugfix` engine stage) must still force test files in.
    without_workflow = create_workset(tmp_path, "wf-test-a", "update Widget")
    with_workflow = create_workset(tmp_path, "wf-test-b", "update Widget", workflow="bugfix")

    without_paths = [f["path"] for f in without_workflow["files"]]
    with_paths = [f["path"] for f in with_workflow["files"]]

    assert with_workflow["workflow"] == "bugfix"
    assert "tests/WidgetTest.py" not in without_paths
    assert "tests/WidgetTest.py" in with_paths


def test_refresh_workset_reuses_persisted_workflow(tmp_path):
    from forge.worksets.manager import create_workset, refresh_workset

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Widget.py").write_text("class Widget:\n    pass\n")

    create_workset(tmp_path, "wf-test", "update Widget", workflow="bugfix")
    refreshed = refresh_workset(tmp_path, "wf-test")

    assert refreshed["workflow"] == "bugfix"
