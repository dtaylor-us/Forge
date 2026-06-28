"""Repository characteristic detection."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from forge.repository.ignore import filter_dir_names, normalize_root


@dataclass(frozen=True)
class RepositoryDetection:
    """Detected repository characteristics."""

    root_path: Path
    languages: list[str] = field(default_factory=list)
    build_systems: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    source_roots: list[Path] = field(default_factory=list)
    test_roots: list[Path] = field(default_factory=list)
    important_files: list[Path] = field(default_factory=list)


IMPORTANT_FILE_NAMES = {
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "pom.xml",
    "build.gradle",
    "settings.gradle",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "angular.json",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Chart.yaml",
}


def detect_repository(root: Path | str | None = None) -> RepositoryDetection:
    """Detect project type, build tooling, frameworks, and important roots."""
    root_path = normalize_root(root)
    files = _collect_files(root_path)
    relative_files = [path.relative_to(root_path) for path in files]
    file_names = {path.name for path in files}
    relative_names = {path.as_posix() for path in relative_files}
    suffixes = {path.suffix for path in files}

    languages = _detect_languages(file_names, suffixes)
    build_systems = _detect_build_systems(file_names)
    package_managers = _detect_package_managers(file_names)
    frameworks = _detect_frameworks(root_path, files, file_names, relative_names)
    source_roots = _detect_roots(root_path, files, source=True)
    test_roots = _detect_roots(root_path, files, source=False)
    important_files = sorted(
        [path for path in relative_files if path.name in IMPORTANT_FILE_NAMES],
        key=lambda path: path.as_posix(),
    )

    return RepositoryDetection(
        root_path=root_path,
        languages=sorted(languages),
        build_systems=sorted(build_systems),
        package_managers=sorted(package_managers),
        frameworks=sorted(frameworks),
        source_roots=source_roots,
        test_roots=test_roots,
        important_files=important_files,
    )


def _collect_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current_root, dir_names, file_names in os.walk(root):
        filter_dir_names(dir_names)
        current_path = Path(current_root)
        files.extend(current_path / file_name for file_name in file_names)
    return files


def _detect_languages(file_names: set[str], suffixes: set[str]) -> set[str]:
    languages: set[str] = set()
    if {"pyproject.toml", "requirements.txt"} & file_names or ".py" in suffixes:
        languages.add("Python")
    if {"pom.xml", "build.gradle"} & file_names or ".java" in suffixes:
        languages.add("Java")
    if {"package.json", "angular.json"} & file_names or {".js", ".jsx"} & suffixes:
        languages.add("JavaScript")
    if ".ts" in suffixes or ".tsx" in suffixes:
        languages.add("TypeScript")
    if "Dockerfile" in file_names:
        languages.add("Docker")
    return languages


def _detect_build_systems(file_names: set[str]) -> set[str]:
    build_systems: set[str] = set()
    if "pyproject.toml" in file_names:
        build_systems.add("pyproject")
    if "pom.xml" in file_names:
        build_systems.add("Maven")
    if "build.gradle" in file_names or "settings.gradle" in file_names:
        build_systems.add("Gradle")
    if "package.json" in file_names:
        build_systems.add("npm scripts")
    if "Dockerfile" in file_names:
        build_systems.add("Docker")
    if "Chart.yaml" in file_names:
        build_systems.add("Helm")
    return build_systems


def _detect_package_managers(file_names: set[str]) -> set[str]:
    package_managers: set[str] = set()
    if "requirements.txt" in file_names or "pyproject.toml" in file_names:
        package_managers.add("pip")
    if "package-lock.json" in file_names or "package.json" in file_names:
        package_managers.add("npm")
    if "pnpm-lock.yaml" in file_names:
        package_managers.add("pnpm")
    if "yarn.lock" in file_names:
        package_managers.add("yarn")
    if "pom.xml" in file_names:
        package_managers.add("Maven")
    if "build.gradle" in file_names:
        package_managers.add("Gradle")
    return package_managers


def _detect_frameworks(
    root: Path,
    files: list[Path],
    file_names: set[str],
    relative_names: set[str],
) -> set[str]:
    frameworks: set[str] = set()
    if "angular.json" in file_names:
        frameworks.add("Angular")
    has_react = _package_json_has_dependency(root / "package.json", "react")
    if "package.json" in file_names and has_react:
        frameworks.add("React")
    if _has_spring_marker(files) or {"application.yml", "application.properties"} & file_names:
        frameworks.add("Spring Boot")
    if "Dockerfile" in file_names or {"docker-compose.yml", "docker-compose.yaml"} & file_names:
        frameworks.add("Docker")
    if _has_kubernetes_marker(relative_names, file_names):
        frameworks.add("Kubernetes")
    return frameworks


def _package_json_has_dependency(path: Path, dependency: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    dependencies = payload.get("dependencies") if isinstance(payload, dict) else None
    dev_dependencies = payload.get("devDependencies") if isinstance(payload, dict) else None
    if not isinstance(dependencies, dict):
        dependencies = {}
    if not isinstance(dev_dependencies, dict):
        dev_dependencies = {}
    return dependency in dependencies or dependency in dev_dependencies


def _has_spring_marker(files: list[Path]) -> bool:
    for path in files:
        if path.suffix != ".java":
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "@SpringBootApplication" in content or "@RestController" in content:
            return True
    return False


def _has_kubernetes_marker(relative_names: set[str], file_names: set[str]) -> bool:
    if any(name.startswith(("k8s/", "charts/")) for name in relative_names):
        return True
    if "Chart.yaml" in file_names:
        return True
    return bool({"deployment.yaml", "deployment.yml"} & file_names)


def _detect_roots(root: Path, files: list[Path], *, source: bool) -> list[Path]:
    candidates = (
        [
            "src",
            "app",
            "forge",
            "lib",
            "src/main/java",
        ]
        if source
        else [
            "tests",
            "test",
            "src/test/java",
        ]
    )
    roots = [Path(candidate) for candidate in candidates if (root / candidate).is_dir()]
    if roots:
        return roots

    suffixes = {".py", ".java", ".js", ".jsx", ".ts", ".tsx"}
    inferred = {
        path.parent.relative_to(root)
        for path in files
        if path.suffix in suffixes and path.parent != root
    }
    if source:
        inferred = {
            path for path in inferred if "test" not in path.parts and "tests" not in path.parts
        }
    else:
        inferred = {path for path in inferred if "test" in path.parts or "tests" in path.parts}
    return sorted(inferred, key=lambda path: path.as_posix())[:10]
