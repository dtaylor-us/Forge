"""Deterministic verification strategy detection."""

from __future__ import annotations

import json
import os
import tomllib
from contextlib import suppress
from pathlib import Path
from typing import Any

from forge.repository.ignore import filter_dir_names, normalize_root
from forge.verification.models import (
    VerificationConfidence,
    VerificationEcosystem,
    VerificationStep,
    VerificationStrategy,
    VerificationTool,
)


def detect_verification_strategy(root: Path | str | None = None) -> VerificationStrategy:
    """Detect a repository verification strategy without executing commands."""
    root_path = normalize_root(root)
    file_names = _collect_file_names(root_path)

    if _has_python_signal(root_path, file_names):
        return _detect_python(root_path, file_names)
    if "package.json" in file_names:
        return _detect_node(root_path, file_names)
    if "pom.xml" in file_names:
        return _detect_maven(root_path, file_names)
    if {"build.gradle", "build.gradle.kts", "gradlew"} & file_names:
        return _detect_gradle(file_names)
    if "go.mod" in file_names:
        return _strategy(
            VerificationEcosystem.go,
            VerificationConfidence.high,
            [VerificationStep("tests", "go test ./...", "tests", VerificationTool.go)],
            signals=["go.mod"],
        )
    if "Cargo.toml" in file_names:
        return _strategy(
            VerificationEcosystem.rust,
            VerificationConfidence.high,
            [
                VerificationStep("tests", "cargo test", "tests", VerificationTool.cargo),
                VerificationStep("linter", "cargo clippy", "linter", VerificationTool.cargo),
                VerificationStep(
                    "formatter",
                    "cargo fmt --check",
                    "formatter",
                    VerificationTool.cargo,
                ),
            ],
            package_manager="cargo",
            signals=["Cargo.toml"],
        )
    if _has_dotnet_signal(root_path, file_names):
        return _detect_dotnet(root_path)
    return _strategy(VerificationEcosystem.unknown, VerificationConfidence.unknown, [])


def _collect_file_names(root: Path) -> set[str]:
    file_names: set[str] = set()
    for _current_root, dir_names, names in os.walk(root):
        filter_dir_names(dir_names)
        file_names.update(names)
    return file_names


def _has_python_signal(root: Path, file_names: set[str]) -> bool:
    return bool(
        {"pyproject.toml", "pytest.ini", "requirements.txt", "setup.py", "ruff.toml", ".ruff.toml"}
        & file_names
        or list(root.rglob("*.py"))
    )


def _detect_python(root: Path, file_names: set[str]) -> VerificationStrategy:
    pyproject = _read_pyproject(root / "pyproject.toml")
    dependency_names = _python_dependency_names(root, pyproject)
    signals = sorted(
        {
            name
            for name in (
                "pyproject.toml",
                "pytest.ini",
                "requirements.txt",
                "setup.py",
                "ruff.toml",
                ".ruff.toml",
            )
            if name in file_names
        }
    )
    steps: list[VerificationStep] = []
    has_pytest = (
        "pytest.ini" in file_names
        or "pytest" in dependency_names
        or _pyproject_has_tool(pyproject, "pytest")
    )
    if has_pytest:
        steps.append(VerificationStep("tests", "pytest", "tests", VerificationTool.pytest))
    if (
        {"ruff.toml", ".ruff.toml"} & file_names
        or "ruff" in dependency_names
        or _pyproject_has_tool(pyproject, "ruff")
    ):
        steps.append(VerificationStep("linter", "ruff check .", "linter", VerificationTool.ruff))
    if "black" in dependency_names or _pyproject_has_tool(pyproject, "black"):
        steps.append(
            VerificationStep("formatter", "black --check .", "formatter", VerificationTool.black)
        )
    return _strategy(
        VerificationEcosystem.python,
        VerificationConfidence.high if steps else VerificationConfidence.medium,
        steps,
        package_manager="pip",
        signals=signals,
    )


def _detect_node(root: Path, file_names: set[str]) -> VerificationStrategy:
    package_manager = _node_package_manager(file_names)
    payload = _read_json(root / "package.json")
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    if not isinstance(scripts, dict):
        scripts = {}
    steps: list[VerificationStep] = []
    tool = VerificationTool(package_manager)
    if "build" in scripts:
        steps.append(VerificationStep("build", f"{package_manager} run build", "build", tool))
    if "test" in scripts:
        steps.append(VerificationStep("tests", f"{package_manager} test", "tests", tool))
    if "lint" in scripts:
        steps.append(VerificationStep("linter", f"{package_manager} run lint", "linter", tool))
    signals = ["package.json"]
    signals.extend(
        name for name in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock") if name in file_names
    )
    return _strategy(
        VerificationEcosystem.node,
        VerificationConfidence.high,
        steps,
        package_manager=package_manager,
        signals=signals,
    )


def _detect_maven(root: Path, file_names: set[str]) -> VerificationStrategy:
    command = "./mvnw verify" if "mvnw" in file_names or (root / "mvnw").exists() else "mvn verify"
    signals = ["pom.xml"]
    if command.startswith("./"):
        signals.append("mvnw")
    return _strategy(
        VerificationEcosystem.maven,
        VerificationConfidence.high,
        [VerificationStep("build", command, "build", VerificationTool.maven)],
        package_manager="maven",
        signals=signals,
    )


def _detect_gradle(file_names: set[str]) -> VerificationStrategy:
    command = "./gradlew build" if "gradlew" in file_names else "gradle build"
    signals = [
        name for name in ("build.gradle", "build.gradle.kts", "gradlew") if name in file_names
    ]
    return _strategy(
        VerificationEcosystem.gradle,
        VerificationConfidence.high,
        [VerificationStep("tests", command, "tests", VerificationTool.gradle)],
        package_manager="gradle",
        signals=signals,
    )


def _detect_dotnet(root: Path) -> VerificationStrategy:
    signals = sorted(path.name for path in root.rglob("*.sln"))
    signals.extend(sorted(path.name for path in root.rglob("*.csproj")))
    return _strategy(
        VerificationEcosystem.dotnet,
        VerificationConfidence.high,
        [
            VerificationStep("build", "dotnet build", "build", VerificationTool.dotnet),
            VerificationStep("tests", "dotnet test", "tests", VerificationTool.dotnet),
        ],
        package_manager="dotnet",
        signals=signals,
    )


def _node_package_manager(file_names: set[str]) -> str:
    if "pnpm-lock.yaml" in file_names:
        return "pnpm"
    if "yarn.lock" in file_names:
        return "yarn"
    return "npm"


def _has_dotnet_signal(root: Path, file_names: set[str]) -> bool:
    return ".sln" in {Path(name).suffix for name in file_names} or any(root.rglob("*.csproj"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_pyproject(path: Path) -> dict[str, Any]:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _python_dependency_names(root: Path, pyproject: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    names.update(_dependency_names_from_values(_pyproject_dependency_values(pyproject)))
    requirements = root / "requirements.txt"
    if requirements.exists():
        with suppress(OSError):
            names.update(
                _dependency_names_from_values(requirements.read_text(encoding="utf-8").splitlines())
            )
    setup_py = root / "setup.py"
    if setup_py.exists():
        try:
            content = setup_py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        for candidate in ("pytest", "ruff", "black"):
            if candidate in content:
                names.add(candidate)
    return names


def _pyproject_dependency_values(pyproject: dict[str, Any]) -> list[str]:
    values: list[str] = []
    project = pyproject.get("project")
    if isinstance(project, dict):
        dependencies = project.get("dependencies")
        if isinstance(dependencies, list):
            values.extend(str(dependency) for dependency in dependencies)
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list):
                    values.extend(str(dependency) for dependency in group)
    return values


def _dependency_names_from_values(values: list[str]) -> set[str]:
    names: set[str] = set()
    for value in values:
        stripped = value.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name = ""
        for character in stripped:
            if character.isalnum() or character in {"-", "_", "."}:
                name += character
            else:
                break
        if name:
            names.add(name.lower().replace("_", "-"))
    return names


def _pyproject_has_tool(pyproject: dict[str, Any], name: str) -> bool:
    tool = pyproject.get("tool")
    return isinstance(tool, dict) and name in tool


def _strategy(
    ecosystem: VerificationEcosystem,
    confidence: VerificationConfidence,
    steps: list[VerificationStep],
    *,
    package_manager: str | None = None,
    signals: list[str] | None = None,
) -> VerificationStrategy:
    return VerificationStrategy(
        ecosystem=ecosystem,
        confidence=confidence,
        package_manager=package_manager,
        steps=steps,
        signals=signals or [],
    )
