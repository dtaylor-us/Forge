"""Tests for forge implement patch generation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from forge.cli.app import app
from forge.execution import ExecutionService
from forge.execution.execution_prompt import build_implementation_prompt
from forge.models.errors import ModelProviderError
from forge.models.types import ModelResponse
from forge.planning.planner import ImplementationPlan
from forge.services.implementation_service import ImplementationService
from forge.worksets.store import load, save

runner = CliRunner()

TASK = "Add greeting"
WORKSET = "greeting"

VALID_DIFF = """diff --git a/forge/example.py b/forge/example.py
index 1111111..2222222 100644
--- a/forge/example.py
+++ b/forge/example.py
@@ -1 +1 @@
-print("old")
+print("new")
"""


class FakeModelManager:
    def __init__(
        self, content: str = VALID_DIFF, *, fail: bool = False, truncated: bool = False
    ) -> None:
        self.content = content
        self.fail = fail
        self.truncated = truncated
        self.prompts: list[tuple[str, str | None, int | None]] = []

    def config(self):
        return SimpleNamespace(default_model="fake-model")

    def ask(
        self,
        prompt: str,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> ModelResponse:
        self.prompts.append((prompt, model, timeout_seconds))
        if self.fail:
            raise ModelProviderError("provider unavailable")
        return ModelResponse(
            content=self.content,
            model=model or "fake-model",
            provider="fake",
            truncated=self.truncated,
        )


def _make_workset(root: Path) -> Path:
    source = root / "forge" / "example.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('print("old")\n', encoding="utf-8")
    save(
        root,
        {
            "schema_version": 1,
            "name": WORKSET,
            "query": "greeting example",
            "root": str(root),
            "created_at": "2026-06-28T00:00:00+00:00",
            "updated_at": "2026-06-28T00:00:00+00:00",
            "include_tests": False,
            "max_results": 10,
            "files": [
                {
                    "path": "forge/example.py",
                    "score": 20,
                    "category": "source",
                    "reasons": [{"signal": "filename", "detail": "example", "points": 20}],
                    "manual": False,
                }
            ],
        },
    )
    return source


def test_implementation_prompt_requires_unified_diff_only(tmp_path: Path) -> None:
    _make_workset(tmp_path)
    manager = FakeModelManager()
    plan = ImplementationPlan(
        task=TASK,
        workset_name=WORKSET,
        model="fake-model",
        generated_at=datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC),
        content="Update forge/example.py.",
    )
    request = ExecutionService(manager).create_request(
        tmp_path,
        TASK,
        WORKSET,
        implementation_plan=plan,
    )

    prompt, warning = build_implementation_prompt(
        TASK,
        request.context_bundle,
        request.implementation_plan,
        request.selected_model,
        request.related_memory,
    )

    assert warning is None
    assert "Return only a raw unified diff" in prompt
    assert "No Markdown fences" in prompt
    assert "No explanations" in prompt
    assert "Prefer files from the workset" in prompt
    assert "Include valid hunk markers" in prompt
    assert "Use paths relative to the repository root" in prompt


def test_search_replace_prompt_uses_budgeted_context_and_edit_targets(tmp_path: Path) -> None:
    from forge.execution.execution_prompt import build_search_replace_prompt

    bundle = SimpleNamespace(
        workset_name="budget-ws",
        query="fix Big",
        root=str(tmp_path),
        generated_at="2026-01-01T00:00:00Z",
        files=[
            SimpleNamespace(
                path="src/Big.java",
                category="source",
                score=90,
                line_count=500,
                char_count=20_000,
                symbols=["Big"],
                error=None,
                summary=["large source"],
                dependency_hints=[],
                reasons=["identifier:Big (+20)"],
                excerpts=[f"line {i}" for i in range(1, 401)],
            ),
            SimpleNamespace(
                path="README.md",
                category="docs",
                score=20,
                line_count=50,
                char_count=1000,
                symbols=[],
                error=None,
                summary=["docs"],
                dependency_hints=[],
                reasons=[],
                excerpts=[f"doc {i}" for i in range(1, 51)],
            ),
        ],
    )
    plan = SimpleNamespace(content="Update src/Big.java.")

    prompt, warning = build_search_replace_prompt("fix Big.java", bundle, plan, "model-x")

    assert warning is None
    assert "# Edit Targeting Plan" in prompt
    assert "# Approved Editable Files" in prompt
    assert "You may ONLY emit SEARCH/REPLACE blocks" in prompt
    assert "Any block for any other file will be rejected." in prompt
    assert "unless unavoidable" not in prompt
    assert "| src/Big.java | modify |" in prompt
    assert "Content mode: focused excerpt" in prompt
    assert "Reason: large primary target, budget-limited" in prompt
    # README.md is not an approved editable target (no strong identifier match
    # for it), so it must appear only in the context-only summary table — no
    # "###" file-content header, no verbatim/line-numbered source.
    assert "# Context-Only Files" in prompt
    assert "You may NOT emit SEARCH/REPLACE blocks for them." in prompt
    assert "| README.md | docs |" in prompt
    assert "### README.md" not in prompt
    assert "doc 1" not in prompt


def test_valid_model_diff_is_saved_as_patch(tmp_path: Path) -> None:
    _make_workset(tmp_path)
    manager = FakeModelManager()
    result = ImplementationService(manager).implement(
        tmp_path, TASK, WORKSET, output_format="unified_diff"
    )

    assert result.valid is True
    assert result.status == "accepted"
    assert result.patch_path.parent == tmp_path / ".forge" / "patches"
    assert result.affected_files == ["forge/example.py"]
    assert result.patch_path.read_text(encoding="utf-8") == VALID_DIFF
    assert len(manager.prompts) == 1


def test_invalid_model_response_is_saved_under_invalid_patches(tmp_path: Path) -> None:
    _make_workset(tmp_path)
    result = ImplementationService(FakeModelManager("This is not a diff.")).implement(
        tmp_path,
        TASK,
        WORKSET,
    )

    assert result.valid is False
    assert result.status == "rejected"
    assert result.patch_path is None
    assert result.raw_response_path.parent == tmp_path / ".forge" / "patches" / "invalid"
    assert result.validation_errors
    assert result.raw_response_path.read_text(encoding="utf-8") == "This is not a diff.\n"


def test_output_writes_to_explicit_path(tmp_path: Path) -> None:
    _make_workset(tmp_path)
    output = tmp_path / "review" / "change.patch"

    result = ImplementationService(FakeModelManager()).implement(
        tmp_path,
        TASK,
        WORKSET,
        output_path=output,
        output_format="unified_diff",
    )

    assert result.valid is True
    assert result.patch_path == output
    assert output.read_text(encoding="utf-8") == VALID_DIFF


def test_cli_json_output_includes_patch_metadata(monkeypatch, tmp_path: Path) -> None:
    _make_workset(tmp_path)
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: FakeModelManager())

    result = runner.invoke(
        app,
        [
            "implement",
            TASK,
            "--workset",
            WORKSET,
            "--root",
            str(tmp_path),
            "--output-format",
            "unified_diff",
            "--json",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["task"] == TASK
    assert data["workset"] == WORKSET
    assert data["model"] == "fake-model"
    assert data["status"] == "accepted"
    assert data["valid"] is True
    assert data["affected_files"] == ["forge/example.py"]
    assert data["patch_name"].endswith(".patch")
    assert data["raw_response_path"] is None
    assert data["next_command"].startswith("forge patch show ")


def test_cli_invalid_model_output_exits_nonzero_and_reports_raw_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_workset(tmp_path)
    monkeypatch.setattr(
        "forge.cli.app._model_manager",
        lambda: FakeModelManager("Here is a change summary, not a patch."),
    )

    result = runner.invoke(
        app,
        ["implement", TASK, "--workset", WORKSET, "--root", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Status: rejected" in result.output
    assert "Invalid artifact path:" in result.output
    assert "No patch was accepted." in result.output


def test_cli_json_invalid_model_output_includes_raw_response_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_workset(tmp_path)
    monkeypatch.setattr(
        "forge.cli.app._model_manager",
        lambda: FakeModelManager("Here is a change summary, not a patch."),
    )

    result = runner.invoke(
        app,
        ["implement", TASK, "--workset", WORKSET, "--root", str(tmp_path), "--json"],
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "rejected"
    assert data["valid"] is False
    assert data["patch_path"] is None
    assert data["patch_name"] is None
    assert data["raw_response_path"].endswith(".txt")
    assert data["next_command"] is None


def test_no_repository_source_files_are_modified(tmp_path: Path) -> None:
    source = _make_workset(tmp_path)
    before = source.read_text(encoding="utf-8")

    result = ImplementationService(FakeModelManager()).implement(
        tmp_path, TASK, WORKSET, output_format="unified_diff"
    )

    assert result.valid is True
    assert source.read_text(encoding="utf-8") == before


def test_provider_failure_exits_cleanly(monkeypatch, tmp_path: Path) -> None:
    _make_workset(tmp_path)
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: FakeModelManager(fail=True))

    result = runner.invoke(
        app,
        ["implement", TASK, "--workset", WORKSET, "--root", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Provider error:" in result.output
    assert "provider unavailable" in result.output


def test_missing_workset_exits_cleanly(monkeypatch, tmp_path: Path) -> None:
    manager = FakeModelManager()
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: manager)

    result = runner.invoke(
        app,
        ["implement", TASK, "--workset", "missing", "--root", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Execution error:" in result.output
    assert "missing" in result.output
    assert manager.prompts == []


def test_existing_patch_commands_work_with_generated_patches(monkeypatch, tmp_path: Path) -> None:
    _make_workset(tmp_path)
    monkeypatch.setattr("forge.cli.app._model_manager", lambda: FakeModelManager())
    implement = runner.invoke(
        app,
        [
            "implement",
            TASK,
            "--workset",
            WORKSET,
            "--root",
            str(tmp_path),
            "--output-format",
            "unified_diff",
            "--json",
        ],
    )
    patch_name = json.loads(implement.output)["patch_name"]

    listed = runner.invoke(app, ["patch", "list", "--root", str(tmp_path), "--json"])
    shown = runner.invoke(app, ["patch", "show", patch_name, "--root", str(tmp_path)])
    validated = runner.invoke(app, ["patch", "validate", patch_name, "--root", str(tmp_path)])

    assert listed.exit_code == 0
    assert json.loads(listed.output)[0]["name"] == patch_name
    assert shown.exit_code == 0
    assert "diff --git a/forge/example.py b/forge/example.py" in shown.output
    assert validated.exit_code == 0
    assert "valid" in validated.output


def test_implementation_prompt_includes_test_guidance_when_task_mentions_tests(
    tmp_path: Path,
) -> None:
    bundle = SimpleNamespace(
        workset_name="my-workset",
        query="tests",
        root=str(tmp_path),
        generated_at="2026-01-01T00:00:00Z",
        files=[
            SimpleNamespace(
                path="tests/test_calc.py",
                category="test",
                score=10,
                line_count=12,
                symbols=[],
                error=None,
                summary=[],
                dependency_hints=[],
                excerpts=[],
            )
        ],
    )
    plan = SimpleNamespace(content="add subtract tests")

    prompt, warning = build_implementation_prompt(
        "add subtract function and tests",
        bundle,
        plan,
        "model-x",
    )

    assert "Test File Requirement" in prompt
    assert warning is None


def test_implementation_prompt_warns_when_no_test_files_in_workset(
    tmp_path: Path,
) -> None:
    bundle = SimpleNamespace(
        workset_name="my-workset",
        query="tests",
        root=str(tmp_path),
        generated_at="2026-01-01T00:00:00Z",
        files=[
            SimpleNamespace(
                path="src/calc.py",
                category="source",
                score=10,
                line_count=12,
                symbols=[],
                error=None,
                summary=[],
                dependency_hints=[],
                excerpts=[],
            )
        ],
    )
    plan = SimpleNamespace(content="add tests")

    prompt, warning = build_implementation_prompt("add subtract tests", bundle, plan, "model-x")

    assert "Test File Warning" in prompt
    assert warning is not None
    assert "no test files" in warning.lower()


def test_implementation_prompt_no_warning_when_task_has_no_test_mention(
    tmp_path: Path,
) -> None:
    bundle = SimpleNamespace(
        workset_name="my-workset",
        query="calc",
        root=str(tmp_path),
        generated_at="2026-01-01T00:00:00Z",
        files=[],
    )
    plan = SimpleNamespace(content="add subtract")

    prompt, warning = build_implementation_prompt("add subtract function", bundle, plan, "model-x")

    assert "Test File" not in prompt
    assert warning is None


def test_invalid_first_patch_triggers_repair(tmp_path: Path) -> None:
    valid_response = MagicMock(content=VALID_DIFF, model="test-model")
    invalid_response = MagicMock(content="This is not a patch at all.", model="test-model")
    manager = MagicMock()
    manager.config.return_value.default_model = "test-model"
    manager.ask.side_effect = [invalid_response, valid_response]

    svc = ImplementationService(manager)
    with (
        patch.object(svc._execution_service, "create_request") as mock_req,
        patch("forge.services.implementation_service.apply_check_patch_content") as mock_check,
        patch("forge.services.implementation_service._bundle_file_details", return_value=""),
        patch("forge.services.implementation_service._save_valid_patch") as mock_save,
    ):
        mock_req.return_value.context_bundle = SimpleNamespace(
            workset_name="my-workset",
            query="add subtract",
            root=str(tmp_path),
            generated_at="2026-01-01T00:00:00Z",
            files=[],
        )
        mock_req.return_value.implementation_plan = SimpleNamespace(content="plan")
        mock_req.return_value.selected_model = "test-model"
        mock_req.return_value.related_memory = None
        mock_check.return_value = (True, "")
        mock_save.return_value = SimpleNamespace(
            path=tmp_path / ".forge" / "patches" / "x.patch",
            valid=True,
            affected_files=["forge/example.py"],
            validation_errors=[],
            name="x.patch",
        )

        result = svc.implement(
            tmp_path, "add subtract", "my-workset", repair_attempts=1, output_format="unified_diff"
        )

    assert result.valid is True
    assert result.repair_attempts_made == 1
    assert manager.ask.call_count == 2


def test_repair_exhausted_saves_invalid_artifact(tmp_path: Path) -> None:
    bad_response = MagicMock(content="not a patch", model="test-model")
    manager = MagicMock()
    manager.config.return_value.default_model = "test-model"
    manager.ask.return_value = bad_response

    svc = ImplementationService(manager)
    with (
        patch.object(svc._execution_service, "create_request") as mock_req,
        patch(
            "forge.services.implementation_service.apply_check_patch_content",
            return_value=(False, "error"),
        ),
        patch("forge.services.implementation_service._bundle_file_details", return_value=""),
    ):
        mock_req.return_value.context_bundle = SimpleNamespace(
            workset_name="my-workset",
            query="add subtract",
            root=str(tmp_path),
            generated_at="2026-01-01T00:00:00Z",
            files=[],
        )
        mock_req.return_value.implementation_plan = SimpleNamespace(content="plan")
        mock_req.return_value.selected_model = "test-model"
        mock_req.return_value.related_memory = None

        result = svc.implement(
            tmp_path, "add subtract", "my-workset", repair_attempts=2, output_format="unified_diff"
        )

    assert result.valid is False
    assert result.repair_attempts_made == 2
    assert manager.ask.call_count == 3
    assert result.raw_response_path is not None


def test_repair_prompt_contains_original_patch_and_errors() -> None:
    from forge.execution.execution_prompt import build_repair_prompt

    prompt = build_repair_prompt(
        task="add subtract",
        original_patch="not a diff",
        structural_errors=["Patch must begin with raw diff content"],
        apply_check_error="corrupt hunk at line 3",
        file_details="file content here",
    )

    assert "not a diff" in prompt
    assert "Patch must begin with raw diff content" in prompt
    assert "corrupt hunk at line 3" in prompt
    assert "add subtract" in prompt


def test_repair_prompt_includes_targeted_excerpts_when_provided() -> None:
    from forge.execution.execution_prompt import build_repair_prompt

    targeted = "### src/Foo.java (lines 160–180)\n```\n  165>>>| // Act & Assert\n```"
    prompt = build_repair_prompt(
        task="fix test",
        original_patch="--- a/Foo.java\n+++ b/Foo.java\n@@ -165 +165 @@\n-old\n+new\n",
        structural_errors=[],
        apply_check_error="patch failed",
        file_details="file content here",
        targeted_file_excerpts=targeted,
    )

    assert "AUTHORITATIVE FILE CONTENT AT MISMATCH LOCATIONS" in prompt
    assert targeted in prompt
    assert "ground truth" in prompt


def test_repair_prompt_omits_targeted_section_when_not_provided() -> None:
    from forge.execution.execution_prompt import build_repair_prompt

    prompt = build_repair_prompt(
        task="fix test",
        original_patch="not a diff",
        structural_errors=[],
        apply_check_error="",
        file_details="file content here",
    )

    assert "AUTHORITATIVE FILE CONTENT" not in prompt


def test_srp_repair_prompt_includes_structured_failures() -> None:
    from forge.execution.execution_prompt import build_search_replace_repair_prompt
    from forge.srp.models import SearchReplaceFailureDetail

    prompt = build_search_replace_repair_prompt(
        task="fix Foo",
        original_response="src/Foo.java\n<<<<<<< SEARCH\nmissing\n=======\nnew\n>>>>>>> REPLACE",
        failures=["src/Foo.java: SEARCH content not found in file."],
        file_details="### src/Foo.java",
        failure_details=[
            SearchReplaceFailureDetail(
                file_path="src/Foo.java",
                error_type="not_found",
                search_preview="missing",
                nearest_match_excerpt="    1>>>| class Foo {}",
                message="not found",
            )
        ],
    )

    assert "Structured Failure Details" in prompt
    assert "error_type: not_found" in prompt
    assert "nearest_match_excerpt" in prompt
    assert "class Foo" in prompt


def test_targeted_disk_excerpts_returns_empty_for_no_mismatches() -> None:
    from forge.services.implementation_service import _targeted_disk_excerpts

    result = _targeted_disk_excerpts(Path("/tmp"), [])
    assert result == ""


def test_targeted_disk_excerpts_reads_correct_lines(tmp_path: Path) -> None:
    from forge.services.implementation_service import _targeted_disk_excerpts

    # Create a fake source file with 50 numbered lines
    src = tmp_path / "src" / "Foo.java"
    src.parent.mkdir()
    lines = [f"line {i}" for i in range(1, 51)]
    src.write_text("\n".join(lines), encoding="utf-8")

    mismatch = (
        "src/Foo.java:25: patch context does not match the real file.\n"
        "    patch expected:    'old line'\n"
        "    file actually has: 'line 25'"
    )

    result = _targeted_disk_excerpts(tmp_path, [mismatch], context_lines=5)

    # Should contain the file path header
    assert "src/Foo.java" in result
    # Should contain line 25 marked with >>>
    assert ">>>" in result
    assert "line 25" in result
    # Should contain surrounding lines (20-30 range with 5 context)
    assert "line 20" in result or "line 21" in result  # start of window
    assert "line 30" in result or "line 29" in result  # end of window


def test_targeted_disk_excerpts_marks_mismatch_line_with_arrow(tmp_path: Path) -> None:
    from forge.services.implementation_service import _targeted_disk_excerpts

    src = tmp_path / "Foo.java"
    src.write_text("\n".join(f"line {i}" for i in range(1, 30)), encoding="utf-8")

    mismatch = "Foo.java:10: patch context does not match the real file.\n    patch expected: 'x'"
    result = _targeted_disk_excerpts(tmp_path, [mismatch], context_lines=3)

    # Line 10 must be marked with >>> and other lines with spaces
    assert ">>>| line 10" in result
    assert "   | line 9" in result or "   | line 11" in result


def test_targeted_disk_excerpts_deduplicates_locations(tmp_path: Path) -> None:
    from forge.services.implementation_service import _targeted_disk_excerpts

    src = tmp_path / "Foo.java"
    src.write_text("\n".join(f"line {i}" for i in range(1, 30)), encoding="utf-8")

    mismatch_a = "Foo.java:10: patch context does not match the real file."
    mismatch_b = "Foo.java:10: patch context does not match the real file."
    result = _targeted_disk_excerpts(tmp_path, [mismatch_a, mismatch_b], context_lines=2)

    # Only one excerpt block for the deduplicated location
    assert result.count("### Foo.java") == 1


def test_repair_loop_uses_targeted_excerpts(tmp_path: Path) -> None:
    """Repair prompts include targeted disk excerpts when context mismatches exist."""
    from forge.services.implementation_service import ImplementationService

    # Create a real source file with 40 lines of known content
    target_file = tmp_path / "src" / "Foo.java"
    target_file.parent.mkdir(parents=True)
    target_file.write_text(
        "\n".join(f"    // real line {i}" for i in range(1, 41)),
        encoding="utf-8",
    )

    # Register it in a workset
    save(
        tmp_path,
        {
            "schema_version": 1,
            "name": "repair-ws",
            "query": "fix Foo",
            "root": str(tmp_path),
            "created_at": "2026-06-28T00:00:00+00:00",
            "updated_at": "2026-06-28T00:00:00+00:00",
            "include_tests": False,
            "max_results": 10,
            "files": [
                {
                    "path": "src/Foo.java",
                    "score": 80,
                    "category": "source",
                    "reasons": [],
                    "manual": False,
                }
            ],
        },
    )

    # Patch whose context lines don't exist in the real file
    bad_patch = (
        "diff --git a/src/Foo.java b/src/Foo.java\n"
        "--- a/src/Foo.java\n"
        "+++ b/src/Foo.java\n"
        "@@ -5,3 +5,3 @@\n"
        " // stale line that does not exist\n"
        "-// old\n"
        "+// new\n"
        " // another stale line\n"
    )

    prompts_seen: list[str] = []

    def _fake_ask(prompt: str, **kwargs: object) -> object:
        prompts_seen.append(prompt)
        return ModelResponse(content=bad_patch, model="test-model", provider="test")

    svc = ImplementationService()
    svc._model_manager.ask = _fake_ask  # type: ignore[method-assign]

    svc.implement(
        tmp_path, "fix Foo", "repair-ws", repair_attempts=1, output_format="unified_diff"
    )

    # The repair prompt (second call) must contain the targeted excerpt section
    assert len(prompts_seen) >= 2, "Expected at least one repair attempt"
    repair_prompt = prompts_seen[1]
    assert "AUTHORITATIVE FILE CONTENT AT MISMATCH LOCATIONS" in repair_prompt


def test_srp_truncated_empty_response_gets_actionable_error(tmp_path: Path) -> None:
    """When the SEARCH/REPLACE path parses zero blocks AND the provider
    reports the response was truncated (output-length/context-window limit),
    the error must say so specifically — not the generic "no blocks found"
    message, which looks identical whether the model was cut off mid-token or
    simply ignored the requested format."""
    _make_workset(tmp_path)
    manager = FakeModelManager(
        "Incomplete output that never reaches a REPLACE marker", truncated=True
    )

    result = ImplementationService(manager).implement(
        tmp_path, TASK, WORKSET, repair_attempts=0, output_format="search_replace"
    )

    assert result.valid is False
    assert any("truncated" in err.lower() for err in result.validation_errors)
    assert any("max_tokens" in err or "context_window" in err for err in result.validation_errors)


def test_srp_empty_response_without_truncation_gets_generic_error(tmp_path: Path) -> None:
    """Without the truncation signal, the original generic message is kept —
    confirms the new diagnostic is additive, not a blanket replacement."""
    _make_workset(tmp_path)
    manager = FakeModelManager("Sorry, I can't help with that.", truncated=False)

    result = ImplementationService(manager).implement(
        tmp_path, TASK, WORKSET, repair_attempts=0, output_format="search_replace"
    )

    assert result.valid is False
    assert any("No SEARCH/REPLACE blocks found" in err for err in result.validation_errors)
    assert not any("truncated" in err.lower() for err in result.validation_errors)


def _make_session_workset(root: Path, *, include_test: bool = True) -> None:
    files = []
    controller = root / "archon-api/src/main/java/com/acme/SessionController.java"
    controller.parent.mkdir(parents=True, exist_ok=True)
    controller.write_text(
        "package com.acme;\n\n"
        "public class SessionController {\n"
        '    String status() { return "old"; }\n'
        "}\n",
        encoding="utf-8",
    )
    files.append(
        {
            "path": "archon-api/src/main/java/com/acme/SessionController.java",
            "score": 80,
            "category": "source",
            "reasons": [],
            "manual": False,
        }
    )
    if include_test:
        test = root / "archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java"
        test.parent.mkdir(parents=True, exist_ok=True)
        test.write_text(
            "package com.acme;\n\n"
            "class SessionControllerIntegrationTest {\n"
            "    void passes() {}\n"
            "}\n",
            encoding="utf-8",
        )
        files.insert(
            0,
            {
                "path": "archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java",
                "score": 100,
                "category": "test",
                "reasons": [],
                "manual": False,
            },
        )
    ui = root / "axiom-ui/src/views/specweaver/SessionView.tsx"
    ui.parent.mkdir(parents=True, exist_ok=True)
    ui.write_text("export function SessionView() { return null; }\n", encoding="utf-8")
    files.append(
        {
            "path": "axiom-ui/src/views/specweaver/SessionView.tsx",
            "score": 40,
            "category": "source",
            "reasons": [],
            "manual": False,
        }
    )
    save(
        root,
        {
            "schema_version": 1,
            "name": "session-fix",
            "query": "fix SessionControllerIntegrationTest",
            "root": str(root),
            "created_at": "2026-06-30T00:00:00+00:00",
            "updated_at": "2026-06-30T00:00:00+00:00",
            "include_tests": True,
            "max_results": 10,
            "files": files,
        },
    )


def test_srp_block_for_approved_file_is_allowed(tmp_path: Path) -> None:
    _make_session_workset(tmp_path)
    response = """archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java
<<<<<<< SEARCH
class SessionControllerIntegrationTest {
    void passes() {}
}
=======
class SessionControllerIntegrationTest {
    void passes() {}
    void failsBeforeFix() {}
}
>>>>>>> REPLACE
"""
    manager = FakeModelManager(response)

    result = ImplementationService(manager).implement(
        tmp_path,
        "fix SessionControllerIntegrationTest",
        "session-fix",
        repair_attempts=0,
        output_format="search_replace",
    )

    assert result.valid is True
    assert result.affected_files == [
        "archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java"
    ]
    assert result.rejected_files == [] or result.rejected_files is None


def test_srp_block_for_disallowed_file_is_rejected_before_apply(tmp_path: Path) -> None:
    _make_session_workset(tmp_path)
    response = """axiom-ui/src/views/specweaver/SessionView.tsx
<<<<<<< SEARCH
export function SessionView() { return null; }
=======
export function SessionView() { return <div />; }
>>>>>>> REPLACE
"""
    manager = FakeModelManager(response)

    with patch("forge.services.implementation_service.apply_blocks") as apply_mock:
        result = ImplementationService(manager).implement(
            tmp_path,
            "fix SessionControllerIntegrationTest",
            "session-fix",
            repair_attempts=0,
            output_format="search_replace",
        )

    apply_mock.assert_not_called()
    assert result.valid is False
    assert result.status == "rejected"
    assert result.rejected_files == ["axiom-ui/src/views/specweaver/SessionView.tsx"]
    assert result.raw_response_path is not None
    assert result.raw_response_path.parent == tmp_path / ".forge" / "patches" / "invalid"
    assert any("outside the approved target set" in err for err in result.validation_errors)
    assert any("SessionControllerIntegrationTest.java" in err for err in result.validation_errors)


def test_required_edit_target_missing_fails_before_model_call(tmp_path: Path) -> None:
    _make_session_workset(tmp_path, include_test=False)
    manager = FakeModelManager("should not be used")

    result = ImplementationService(manager).implement(
        tmp_path,
        "fix SessionControllerIntegrationTest",
        "session-fix",
        repair_attempts=0,
        output_format="search_replace",
    )

    assert result.valid is False
    assert result.status == "rejected"
    assert len(manager.prompts) == 0
    assert any(
        "Required edit target not found in workset: SessionControllerIntegrationTest" in err
        for err in result.validation_errors
    )
    assert result.editable_targets is not None
    assert result.editable_targets.missing_required == ["SessionControllerIntegrationTest"]


# ---------------------------------------------------------------------------
# Implementation prompt target isolation
#
# Workset files != editable prompt files. These tests reproduce the
# `forge workflow bugfix "fix SessionControllerIntegrationTest"` failure
# described in the target-isolation spec: the workset legitimately contains
# DTOs, a repository, an unrelated workshop model, and a cross-module
# controller alongside the two approved editable targets. The implementation
# prompt must hand out full, SEARCH/REPLACE-ready content only for the
# approved targets.
# ---------------------------------------------------------------------------


def _isolation_fixture_files() -> list[SimpleNamespace]:
    def _mk(path: str, *, category: str = "source", score: int = 50) -> SimpleNamespace:
        return SimpleNamespace(
            path=path,
            category=category,
            score=score,
            line_count=10,
            char_count=200,
            symbols=[path.rsplit("/", 1)[-1].split(".")[0]],
            error=None,
            summary=[f"{path} summary"],
            dependency_hints=[],
            reasons=[],
            excerpts=[f"// {path} line {i}" for i in range(1, 11)],
        )

    return [
        _mk(
            "archon-api/src/test/java/com/archon/api/SessionControllerIntegrationTest.java",
            category="test",
            score=100,
        ),
        _mk("archon-api/src/main/java/com/archon/api/controller/SessionController.java", score=90),
        _mk("archon-api/src/main/java/com/archon/api/dto/SessionDto.java", score=60),
        _mk(
            "archon-api/src/main/java/com/archon/api/workshop/domain/model/WorkshopSession.java",
            score=55,
        ),
        _mk(
            "archon-api/src/main/java/com/archon/api/workshop/domain/repository/"
            "WorkshopSessionRepository.java",
            score=55,
        ),
        _mk(
            "archon-api/src/main/java/com/archon/api/workshop/dto/WorkshopSessionDto.java",
            score=55,
        ),
        _mk(
            "lens-api/src/main/java/com/lens/api/controller/ReviewSessionController.java",
            score=40,
        ),
    ]


def test_srp_prompt_isolates_editable_targets_from_cross_module_context() -> None:
    """Reproduces the SessionControllerIntegrationTest bug report end to end."""
    from forge.edit_targets import select_editable_targets
    from forge.execution.execution_prompt import build_search_replace_prompt

    files = _isolation_fixture_files()
    bundle = SimpleNamespace(
        workset_name="session-fix",
        query="fix SessionControllerIntegrationTest",
        root="/repo",
        generated_at="2026-06-30T00:00:00Z",
        files=files,
    )
    plan = SimpleNamespace(content="Fix the failing integration test.")
    task = "fix SessionControllerIntegrationTest"
    editable_targets = select_editable_targets(task, bundle)

    prompt, _ = build_search_replace_prompt(
        task, bundle, plan, "model-x", editable_targets=editable_targets
    )

    approved = [
        "archon-api/src/test/java/com/archon/api/SessionControllerIntegrationTest.java",
        "archon-api/src/main/java/com/archon/api/controller/SessionController.java",
    ]
    non_editable = [
        "archon-api/src/main/java/com/archon/api/dto/SessionDto.java",
        "archon-api/src/main/java/com/archon/api/workshop/domain/model/WorkshopSession.java",
        "archon-api/src/main/java/com/archon/api/workshop/domain/repository/"
        "WorkshopSessionRepository.java",
        "archon-api/src/main/java/com/archon/api/workshop/dto/WorkshopSessionDto.java",
        "lens-api/src/main/java/com/lens/api/controller/ReviewSessionController.java",
    ]

    # Approved editable targets get a "###" content header and their
    # verbatim, line-numbered source.
    for path in approved:
        assert f"### {path}" in prompt
        assert f"// {path} line 1" in prompt

    # None of the non-editable files ever get a content header or their
    # verbatim source, whether they are same-module context or cross-module
    # omitted files.
    for path in non_editable:
        assert f"### {path}" not in prompt
        assert f"// {path} line 1" not in prompt

    # Same-module DTO/repository/model files are surfaced as context-only.
    assert "# Context-Only Files" in prompt
    assert "SessionDto.java" in prompt
    assert "WorkshopSession.java" in prompt
    assert "WorkshopSessionRepository.java" in prompt
    assert "WorkshopSessionDto.java" in prompt

    # The cross-module lens-api controller is omitted from the prompt
    # entirely, surfaced only in the diagnostic omitted-files section.
    assert "# Omitted Workset Files" in prompt
    assert "lens-api/src/main/java/com/lens/api/controller/ReviewSessionController.java" in prompt


def test_workflow_bugfix_prompt_never_sends_full_content_for_non_targets(tmp_path: Path) -> None:
    """Same scenario, exercised through ImplementationService.implement end to end."""
    files_meta = []
    for f in _isolation_fixture_files():
        abs_path = tmp_path / f.path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text("\n".join(f.excerpts) + "\n", encoding="utf-8")
        files_meta.append(
            {
                "path": f.path,
                "score": f.score,
                "category": f.category,
                "reasons": [],
                "manual": False,
            }
        )
    save(
        tmp_path,
        {
            "schema_version": 1,
            "name": "session-fix",
            "query": "fix SessionControllerIntegrationTest",
            "root": str(tmp_path),
            "created_at": "2026-06-30T00:00:00+00:00",
            "updated_at": "2026-06-30T00:00:00+00:00",
            "include_tests": True,
            "max_results": 20,
            "files": files_meta,
        },
    )
    manager = FakeModelManager("no valid blocks")

    ImplementationService(manager).implement(
        tmp_path,
        "fix SessionControllerIntegrationTest",
        "session-fix",
        repair_attempts=0,
        output_format="search_replace",
    )

    assert len(manager.prompts) == 1
    sent_prompt = manager.prompts[0][0]
    assert (
        "### archon-api/src/main/java/com/archon/api/controller/SessionController.java"
        in sent_prompt
    )
    for path in (
        "archon-api/src/main/java/com/archon/api/dto/SessionDto.java",
        "archon-api/src/main/java/com/archon/api/workshop/domain/model/WorkshopSession.java",
        "lens-api/src/main/java/com/lens/api/controller/ReviewSessionController.java",
    ):
        assert f"### {path}" not in sent_prompt


def test_feature_workflow_without_strong_identifier_still_gets_full_content() -> None:
    """Regression: tasks without a strong identifier still get editable content."""
    from forge.edit_targets import select_editable_targets
    from forge.execution.execution_prompt import build_search_replace_prompt

    files = [
        SimpleNamespace(
            path="forge/services/foo_service.py",
            category="source",
            score=40,
            line_count=20,
            char_count=400,
            symbols=["FooService"],
            error=None,
            summary=["foo service"],
            dependency_hints=[],
            reasons=[],
            excerpts=[f"line {i}" for i in range(1, 21)],
        ),
        SimpleNamespace(
            path="forge/services/bar_service.py",
            category="source",
            score=35,
            line_count=15,
            char_count=300,
            symbols=["BarService"],
            error=None,
            summary=["bar service"],
            dependency_hints=[],
            reasons=[],
            excerpts=[f"line {i}" for i in range(1, 16)],
        ),
    ]
    bundle = SimpleNamespace(
        workset_name="feature-ws",
        query="add caching to services",
        root="/repo",
        generated_at="2026-06-30T00:00:00Z",
        files=files,
    )
    plan = SimpleNamespace(content="Add caching.")
    task = "add caching to services"
    editable_targets = select_editable_targets(task, bundle)

    prompt, _ = build_search_replace_prompt(
        task, bundle, plan, "model-x", editable_targets=editable_targets
    )

    assert "### forge/services/foo_service.py" in prompt
    assert "### forge/services/bar_service.py" in prompt
    assert "# Omitted Workset Files" not in prompt


def test_docs_workflow_edits_readme_when_explicitly_targeted() -> None:
    """Regression: an explicitly-targeted doc file remains editable."""
    from forge.edit_targets import select_editable_targets
    from forge.execution.execution_prompt import build_search_replace_prompt

    files = [
        SimpleNamespace(
            path="README.md",
            category="docs",
            score=50,
            line_count=10,
            char_count=200,
            symbols=[],
            error=None,
            summary=["readme"],
            dependency_hints=[],
            reasons=[],
            excerpts=[f"doc line {i}" for i in range(1, 11)],
        ),
    ]
    bundle = SimpleNamespace(
        workset_name="docs-ws",
        query="update README",
        root="/repo",
        generated_at="2026-06-30T00:00:00Z",
        files=files,
    )
    plan = SimpleNamespace(content="Update the README.")
    # Lowercase "readme" avoids being parsed as a strong (code) identifier —
    # see forge.edit_targets.selector._is_strong_identifier — so this task
    # exercises the "no strong identifier, but explicitly targeted doc file"
    # branch of select_editable_targets.
    task = "update readme with new install steps"
    editable_targets = select_editable_targets(task, bundle)

    prompt, _ = build_search_replace_prompt(
        task, bundle, plan, "model-x", editable_targets=editable_targets
    )

    assert "### README.md" in prompt
    assert "doc line 1" in prompt


def test_srp_repair_prompt_includes_approved_editable_files() -> None:
    from forge.edit_targets.models import EditableTarget, EditableTargetSet
    from forge.execution.execution_prompt import build_search_replace_repair_prompt

    targets = EditableTargetSet(
        task="fix Foo",
        workset_name="ws",
        targets=[
            EditableTarget(
                path="src/Foo.java",
                reason="exact identifier match: Foo",
                confidence="primary",
                required=True,
            )
        ],
    )

    prompt = build_search_replace_repair_prompt(
        task="fix Foo",
        original_response="src/Foo.java\n<<<<<<< SEARCH\nmissing\n=======\nnew\n>>>>>>> REPLACE",
        failures=["src/Foo.java: SEARCH content not found in file."],
        file_details="### src/Foo.java",
        editable_targets=targets,
    )

    assert "Approved Editable Files" in prompt
    assert "src/Foo.java" in prompt
    assert "exact identifier match: Foo" in prompt


def test_regenerate_prompt_asks_for_regeneration_using_approved_targets_only() -> None:
    from forge.edit_targets.models import EditableTarget, EditableTargetSet
    from forge.execution.execution_prompt import build_search_replace_regenerate_prompt

    targets = EditableTargetSet(
        task="fix Foo",
        workset_name="ws",
        targets=[
            EditableTarget(
                path="src/Foo.java",
                reason="exact identifier match: Foo",
                confidence="primary",
                required=True,
            )
        ],
    )

    prompt = build_search_replace_regenerate_prompt(
        task="fix Foo",
        original_response="bad/Other.java\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE",
        rejected_files=["bad/Other.java"],
        editable_targets=targets,
        file_details="### src/Foo.java\nContent mode: full content",
    )

    assert "Patch Regeneration Request" in prompt
    assert "bad/Other.java" in prompt
    assert "src/Foo.java" in prompt
    assert "solve the task again using only the approved editable files" in prompt
    assert "do not target these again" in prompt.lower()


def test_srp_block_for_context_only_same_module_file_is_rejected(tmp_path: Path) -> None:
    """A same-module (non-cross-module) context-only file is still rejected."""
    _make_session_workset(tmp_path)
    dto = tmp_path / "archon-api/src/main/java/com/acme/SessionDto.java"
    dto.parent.mkdir(parents=True, exist_ok=True)
    dto.write_text(
        "package com.acme;\n\npublic class SessionDto {\n    String id;\n}\n",
        encoding="utf-8",
    )
    data = load(tmp_path, "session-fix")
    data["files"].append(
        {
            "path": "archon-api/src/main/java/com/acme/SessionDto.java",
            "score": 60,
            "category": "source",
            "reasons": [],
            "manual": False,
        }
    )
    save(tmp_path, data)

    response = """archon-api/src/main/java/com/acme/SessionDto.java
<<<<<<< SEARCH
    String id;
=======
    String id;
    String status;
>>>>>>> REPLACE
"""
    manager = FakeModelManager(response)

    with patch("forge.services.implementation_service.apply_blocks") as apply_mock:
        result = ImplementationService(manager).implement(
            tmp_path,
            "fix SessionControllerIntegrationTest",
            "session-fix",
            repair_attempts=0,
            output_format="search_replace",
        )

    apply_mock.assert_not_called()
    assert result.valid is False
    assert result.status == "rejected"
    assert result.rejected_files == ["archon-api/src/main/java/com/acme/SessionDto.java"]
    assert result.context_only_files is not None
    assert "archon-api/src/main/java/com/acme/SessionDto.java" in result.context_only_files


def test_implementation_result_json_includes_isolation_diagnostics(tmp_path: Path) -> None:
    _make_session_workset(tmp_path)
    response = """archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java
<<<<<<< SEARCH
class SessionControllerIntegrationTest {
    void passes() {}
}
=======
class SessionControllerIntegrationTest {
    void passes() {}
    void failsBeforeFix() {}
}
>>>>>>> REPLACE
"""
    manager = FakeModelManager(response)

    result = ImplementationService(manager).implement(
        tmp_path,
        "fix SessionControllerIntegrationTest",
        "session-fix",
        repair_attempts=0,
        output_format="search_replace",
    )

    data = result.to_dict()
    assert (
        "archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java"
        in data["editable_context_files"]
    )
    assert (
        "archon-api/src/main/java/com/acme/SessionController.java"
        in data["editable_context_files"]
    )
    assert "axiom-ui/src/views/specweaver/SessionView.tsx" in data["omitted_files"]


def test_srp_disallowed_file_regenerates_and_recovers(tmp_path: Path) -> None:
    """A disallowed-file attempt triggers regeneration (not repair) and can still succeed."""
    _make_session_workset(tmp_path)

    disallowed_response = MagicMock(
        content=(
            "axiom-ui/src/views/specweaver/SessionView.tsx\n"
            "<<<<<<< SEARCH\n"
            "export function SessionView() { return null; }\n"
            "=======\n"
            "export function SessionView() { return <div />; }\n"
            ">>>>>>> REPLACE\n"
        ),
        model="test-model",
        truncated=False,
    )
    recovered_response = MagicMock(
        content=(
            "archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java\n"
            "<<<<<<< SEARCH\n"
            "class SessionControllerIntegrationTest {\n"
            "    void passes() {}\n"
            "}\n"
            "=======\n"
            "class SessionControllerIntegrationTest {\n"
            "    void passes() {}\n"
            "    void failsBeforeFix() {}\n"
            "}\n"
            ">>>>>>> REPLACE\n"
        ),
        model="test-model",
        truncated=False,
    )
    manager = MagicMock()
    manager.config.return_value.default_model = "test-model"
    manager.ask.side_effect = [disallowed_response, recovered_response]

    result = ImplementationService(manager).implement(
        tmp_path,
        "fix SessionControllerIntegrationTest",
        "session-fix",
        repair_attempts=1,
        output_format="search_replace",
    )

    assert result.valid is True
    assert result.repair_attempts_made == 1
    assert manager.ask.call_count == 2
    second_prompt = manager.ask.call_args_list[1].kwargs["prompt"]
    assert "Patch Regeneration Request" in second_prompt
    assert "axiom-ui/src/views/specweaver/SessionView.tsx" in second_prompt
    # The rejected file's on-disk content must never be resent in the
    # editable/context file-details section of the regenerate prompt.
    assert "### axiom-ui/src/views/specweaver/SessionView.tsx" not in second_prompt
