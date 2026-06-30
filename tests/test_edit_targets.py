"""Tests for deterministic editable target selection."""

from __future__ import annotations

from types import SimpleNamespace

from forge.edit_targets import select_editable_targets


def _bundle(paths: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        workset_name="session-fix",
        files=[
            SimpleNamespace(path=path, category="source", score=50, error=None)
            for path in paths
        ],
    )


def test_session_controller_integration_test_selects_exact_required_target() -> None:
    targets = select_editable_targets(
        "fix SessionControllerIntegrationTest",
        _bundle(
            [
                "archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java",
                "archon-api/src/main/java/com/acme/SessionController.java",
            ]
        ),
    )

    primary = [target for target in targets.targets if target.confidence == "primary"]
    assert [target.path for target in primary] == [
        "archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java"
    ]
    assert primary[0].required is True
    assert targets.missing_required == []


def test_test_identifier_derives_related_implementation_target() -> None:
    targets = select_editable_targets(
        "fix SessionControllerIntegrationTest",
        _bundle(
            [
                "archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java",
                "archon-api/src/main/java/com/acme/SessionController.java",
                "archon-api/src/main/java/com/acme/SessionService.java",
            ]
        ),
    )

    related_paths = {target.path for target in targets.targets if target.confidence == "related"}
    assert "archon-api/src/main/java/com/acme/SessionController.java" in related_paths
    assert "archon-api/src/main/java/com/acme/SessionService.java" in related_paths


def test_related_files_are_restricted_to_same_module_root() -> None:
    targets = select_editable_targets(
        "fix SessionControllerIntegrationTest",
        _bundle(
            [
                "archon-api/src/test/java/com/acme/SessionControllerIntegrationTest.java",
                "archon-api/src/main/java/com/acme/SessionController.java",
                "specweaver-api/src/main/java/com/acme/SessionController.java",
                "axiom-ui/src/views/specweaver/SessionView.tsx",
            ]
        ),
    )

    paths = {target.path for target in targets.targets}
    assert "archon-api/src/main/java/com/acme/SessionController.java" in paths
    assert "specweaver-api/src/main/java/com/acme/SessionController.java" not in paths
    assert "axiom-ui/src/views/specweaver/SessionView.tsx" not in paths


def test_required_target_missing_is_reported() -> None:
    targets = select_editable_targets(
        "fix SessionControllerIntegrationTest",
        _bundle(["archon-api/src/main/java/com/acme/SessionController.java"]),
    )

    assert targets.targets == []
    assert targets.missing_required == ["SessionControllerIntegrationTest"]
