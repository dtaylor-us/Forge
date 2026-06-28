"""Repository inspection service tests."""

from __future__ import annotations

from forge.repository.detect import detect_repository
from forge.repository.files import list_relevant_files
from forge.repository.grep import search_repository
from forge.repository.ignore import is_ignored_path
from forge.repository.tree import generate_tree


def test_ignored_directory_handling(tmp_path) -> None:
    ignored = tmp_path / "node_modules" / "package" / "index.js"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("secret\n", encoding="utf-8")

    assert is_ignored_path(ignored, tmp_path) is True


def test_tree_generation_respects_max_depth(tmp_path) -> None:
    (tmp_path / "src" / "package").mkdir(parents=True)
    (tmp_path / "src" / "package" / "module.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")

    lines = generate_tree(tmp_path, max_depth=1)

    assert any("[D] src/" in line for line in lines)
    assert any("[F] README.md" in line for line in lines)
    assert not any("module.py" in line for line in lines)


def test_detect_python_project(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")

    detection = detect_repository(tmp_path)

    assert "Python" in detection.languages
    assert "pyproject" in detection.build_systems
    assert "pip" in detection.package_managers
    assert "src" in [str(path) for path in detection.source_roots]
    assert "tests" in [str(path) for path in detection.test_roots]
    assert "pyproject.toml" in [str(path) for path in detection.important_files]


def test_detect_java_spring_boot_project(tmp_path) -> None:
    java_root = tmp_path / "src" / "main" / "java" / "com" / "example"
    java_root.mkdir(parents=True)
    (tmp_path / "pom.xml").write_text("<project />\n", encoding="utf-8")
    (java_root / "Application.java").write_text(
        "@SpringBootApplication\nclass Application {}\n",
        encoding="utf-8",
    )
    resources = tmp_path / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application.yml").write_text("server:\n  port: 8080\n", encoding="utf-8")

    detection = detect_repository(tmp_path)

    assert "Java" in detection.languages
    assert "Maven" in detection.build_systems
    assert "Spring Boot" in detection.frameworks


def test_detect_node_react_and_angular_project(tmp_path) -> None:
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"react": "19.0.0"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "angular.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.tsx").write_text("export const App = () => null;\n", encoding="utf-8")

    detection = detect_repository(tmp_path)

    assert "JavaScript" in detection.languages
    assert "TypeScript" in detection.languages
    assert "npm" in detection.package_managers
    assert "React" in detection.frameworks
    assert "Angular" in detection.frameworks


def test_grep_python_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("forge.repository.grep.shutil.which", lambda _: None)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "controller.py").write_text(
        "class ModelManager:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("ModelManager\n", encoding="utf-8")

    matches = search_repository("ModelManager", tmp_path, globs=["*.py"], max_results=5)

    assert [(str(match.path), match.line_number, match.line) for match in matches] == [
        ("src/controller.py", 1, "class ModelManager:")
    ]


def test_relevant_file_listing(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("ignored\n", encoding="utf-8")

    files = [str(path) for path in list_relevant_files(tmp_path, ext="py")]

    assert files == ["src/app.py"]
