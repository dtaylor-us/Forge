"""Project explanation context tests."""

from __future__ import annotations

from forge.commands.project_context import (
    build_guardrailed_ask_prompt,
    build_project_explanation_prompt,
)


def test_guardrailed_ask_prompt_disambiguates_local_forge_project(tmp_path) -> None:
    (tmp_path / "README.md").write_text(
        "# Forge\n\nForge is an AI-native software engineering workbench.\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "forge-workbench"\ndescription = "Local-first AI workbench."\n',
        encoding="utf-8",
    )

    prompt = build_guardrailed_ask_prompt(
        tmp_path, "how could I enhance forge to be a VS Code extension"
    )

    assert "When the user says Forge, interpret it as this local project" in prompt
    assert "Do not assume Autodesk Forge" in prompt
    assert "forge-workbench - Local-first AI workbench." in prompt
    assert "Forge is an AI-native software engineering workbench." in prompt
    assert "how could I enhance forge to be a VS Code extension" in prompt


def test_project_explanation_includes_readme_when_present(tmp_path) -> None:
    (tmp_path / "README.md").write_text("# Forge Example\n", encoding="utf-8")

    prompt = build_project_explanation_prompt(tmp_path)

    assert "File: README.md" in prompt
    assert "# Forge Example" in prompt


def test_project_explanation_includes_pyproject_when_present(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "forge-example"\n', encoding="utf-8"
    )

    prompt = build_project_explanation_prompt(tmp_path)

    assert "File: pyproject.toml" in prompt
    assert 'name = "forge-example"' in prompt


def test_project_explanation_includes_development_log_when_present(tmp_path) -> None:
    log_path = tmp_path / "docs" / "development" / "DEVELOPMENT_LOG.md"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("# Dev Log\n\n- Added tests.\n", encoding="utf-8")

    prompt = build_project_explanation_prompt(tmp_path)

    assert "File: docs/development/DEVELOPMENT_LOG.md" in prompt
    assert "- Added tests." in prompt


def test_project_explanation_excludes_ignored_folders_from_tree_and_context(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    for folder in [".git", ".venv", "target", "build", "node_modules", "dist"]:
        path = tmp_path / folder
        path.mkdir()
        (path / "ignored.txt").write_text("secret\n", encoding="utf-8")

    prompt = build_project_explanation_prompt(tmp_path)

    assert "src/" in prompt
    assert "main.py" in prompt
    assert "ignored.txt" not in prompt
    for folder in [".git", ".venv", "target", "build", "node_modules", "dist"]:
        assert folder not in prompt
