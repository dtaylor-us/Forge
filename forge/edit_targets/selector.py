"""Deterministic editable target selection from an existing workset bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.edit_targets.models import EditableTarget, EditableTargetSet
from forge.worksets.identifiers import normalize_identifier
from forge.worksets.query import BUILD_TERMS, CONFIG_TERMS, DOC_TERMS, parse_query
from forge.worksets.relationships import relationship_for_path, relationship_targets

_CODE_EXTENSIONS = {
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".swift",
    ".ts",
    ".tsx",
}
_DOC_FILENAMES = {"readme", "changelog", "contributing", "license"}
_CONTEXT_ONLY_FILENAMES = {
    "dockerfile",
    "makefile",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pom.xml",
    "build.gradle",
    "settings.gradle",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
}
_CONTEXT_ONLY_EXTENSIONS = {".md", ".rst", ".txt", ".json", ".yaml", ".yml", ".toml", ".xml"}


class EditableTargetSelectionError(Exception):
    """Raised when deterministic editable targets cannot be selected."""


def select_editable_targets(task: str, bundle: Any) -> EditableTargetSet:
    """Select the strict editable-file set from a prepared context bundle."""
    query = parse_query(task)
    files = list(getattr(bundle, "files", []))
    workset_name = str(getattr(bundle, "workset_name", ""))
    strong_identifiers = [i for i in query.identifiers if _is_strong_identifier(i)]

    targets_by_path: dict[str, EditableTarget] = {}
    primary_roots: set[str] = set()
    missing_required: list[str] = []

    for identifier in strong_identifiers:
        matches = _exact_identifier_matches(files, identifier)
        if not matches:
            missing_required.append(identifier)
            continue
        for file in matches:
            path = _file_path(file)
            _put_target(
                targets_by_path,
                EditableTarget(
                    path=path,
                    reason=f"exact identifier match: {identifier}",
                    confidence="primary",
                    required=True,
                ),
            )
            root = _module_root(path)
            if root:
                primary_roots.add(root)

    if not missing_required:
        related_names = relationship_targets(query)
        for file in files:
            path = _file_path(file)
            if path in targets_by_path:
                continue
            if primary_roots and _module_root(path) not in primary_roots:
                continue
            matched = relationship_for_path(Path(path), related_names)
            if matched:
                _put_target(
                    targets_by_path,
                    EditableTarget(
                        path=path,
                        reason=f"related implementation target for {query.subject or task}",
                        confidence="related",
                        required=False,
                    ),
                )

    if not strong_identifiers:
        for file in files:
            path = _file_path(file)
            if path in targets_by_path:
                continue
            if _is_context_only(path) and not _explicitly_targets_context(path, query.raw_query):
                continue
            _put_target(
                targets_by_path,
                EditableTarget(
                    path=path,
                    reason="allowed workset file for task without a strong code identifier",
                    confidence="allowed_context",
                    required=False,
                ),
            )

    return EditableTargetSet(
        task=task,
        workset_name=workset_name,
        targets=list(targets_by_path.values()),
        missing_required=missing_required,
    )


def _put_target(targets: dict[str, EditableTarget], target: EditableTarget) -> None:
    existing = targets.get(target.path)
    if existing is None or _rank(target) < _rank(existing):
        targets[target.path] = target


def _rank(target: EditableTarget) -> int:
    ranks = {"primary": 0, "related": 1, "allowed_context": 2}
    return ranks[target.confidence]


def _exact_identifier_matches(files: list[Any], identifier: str) -> list[Any]:
    normalized = normalize_identifier(identifier)
    return [
        file
        for file in files
        if normalize_identifier(Path(_file_path(file)).stem) == normalized
        and Path(_file_path(file)).suffix.lower() in _CODE_EXTENSIONS
    ]


def _is_strong_identifier(identifier: str) -> bool:
    if "." in identifier or "/" in identifier or "\\" in identifier:
        return True
    return any(ch.isupper() for ch in identifier[1:]) or "_" in identifier or "-" in identifier


def _file_path(file: Any) -> str:
    return str(getattr(file, "path", "")).replace("\\", "/").lstrip("./")


def _module_root(path: str) -> str:
    parts = path.split("/", 1)
    return parts[0] if len(parts) > 1 else ""


def _is_context_only(path: str) -> bool:
    p = Path(path)
    name = p.name.lower()
    stem = p.stem.lower()
    if name in _CONTEXT_ONLY_FILENAMES or stem in _DOC_FILENAMES:
        return True
    if "generated" in path.lower() or "/dist/" in path.lower() or "/build/" in path.lower():
        return True
    return p.suffix.lower() in _CONTEXT_ONLY_EXTENSIONS


def _explicitly_targets_context(path: str, raw_query: str) -> bool:
    lowered = raw_query.lower()
    p = Path(path)
    if p.name.lower() in lowered or p.stem.lower() in lowered:
        return True
    if p.suffix.lower() in {".md", ".rst", ".txt"}:
        return any(term in lowered for term in DOC_TERMS)
    if p.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".xml"}:
        return any(term in lowered for term in CONFIG_TERMS)
    return any(term in lowered for term in BUILD_TERMS)
