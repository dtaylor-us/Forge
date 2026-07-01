"""Deterministic context budgeting for implementation prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forge.context.bundle import ContextBundle, ContextBundleFile
from forge.context.excerpt import OMIT_MARKER
from forge.edit_targets import EditableTargetSet
from forge.execution.edit_plan import EditPlan, derive_edit_plan

implementation_context_window = 12_000
max_full_files = 6
max_lines_large_file = 240
max_lines_secondary_file = 120


@dataclass(frozen=True)
class ContextBudgetConfig:
    """Budget defaults for implementation prompts.

    ``context_window`` is a character approximation, not a tokenizer-specific
    limit.  That keeps budgeting deterministic and provider-independent.
    """

    context_window: int = implementation_context_window
    max_full_files: int = max_full_files
    max_lines_large_file: int = max_lines_large_file
    max_lines_secondary_file: int = max_lines_secondary_file


@dataclass(frozen=True)
class BudgetedFileContext:
    """Rendered context and metadata for one prompt file section."""

    path: str
    content_mode: str
    reason: str
    lines: list[str]
    summary_only: bool = False


def budget_implementation_context(
    task: str,
    bundle: ContextBundle,
    edit_plan: EditPlan | None = None,
    config: ContextBudgetConfig | None = None,
) -> list[BudgetedFileContext]:
    """Choose how much content to include for each workset file."""
    cfg = config or ContextBudgetConfig()
    target_paths = {
        target.file_path
        for target in (edit_plan.targets if edit_plan else [])
        if target.action in {"modify", "create", "delete"} and target.confidence >= 0.7
    }
    task_lower = task.lower()
    ranked = sorted(
        bundle.files,
        key=lambda item: _priority(item, task_lower, target_paths),
        reverse=True,
    )

    remaining = cfg.context_window
    full_count = 0
    rendered: list[BudgetedFileContext] = []

    for file in ranked:
        if getattr(file, "error", None):
            rendered.append(
                BudgetedFileContext(
                    path=file.path,
                    content_mode="metadata only",
                    reason=getattr(file, "error", None),
                    lines=[],
                    summary_only=True,
                )
            )
            continue

        available_lines = [line for line in getattr(file, "excerpts", []) if line != OMIT_MARKER]
        estimated_chars = sum(len(line) + 1 for line in available_lines)
        primary = file.path in target_paths or _task_mentions_path(task_lower, file.path)
        infrastructure = _is_infrastructure_file(file)
        docs_config = _is_docs_or_config_file(file)
        very_large = (
            getattr(file, "line_count", 0) > cfg.max_lines_large_file
            or estimated_chars > remaining
        )

        if (
            primary
            and not very_large
            and full_count < cfg.max_full_files
            and estimated_chars <= remaining
        ):
            mode = "full content"
            reason = "primary target, fits budget"
            selected = available_lines
            full_count += 1
        elif (
            not primary
            and not infrastructure
            and not docs_config
            and not very_large
            and full_count < cfg.max_full_files
            and estimated_chars <= remaining
        ):
            mode = "full content"
            reason = "related file, fits budget"
            selected = available_lines
            full_count += 1
        elif infrastructure and not primary:
            mode = "minimal context"
            reason = "infrastructure file, secondary relevance"
            selected = available_lines[: min(40, cfg.max_lines_secondary_file)]
        elif docs_config and not primary:
            mode = "summary plus excerpt"
            reason = "docs/config file, secondary relevance"
            selected = available_lines[: min(60, cfg.max_lines_secondary_file)]
        elif primary:
            mode = "focused excerpt"
            reason = "large primary target, budget-limited"
            selected = _focused_lines(file, task_lower, cfg.max_lines_large_file)
        else:
            mode = "focused excerpt"
            reason = "large file, secondary relevance"
            selected = _focused_lines(file, task_lower, cfg.max_lines_secondary_file)

        char_cost = sum(len(line) + 1 for line in selected)
        if char_cost > remaining and selected:
            line_budget = max(20, min(len(selected), remaining // 80))
            selected = selected[:line_budget]
            char_cost = sum(len(line) + 1 for line in selected)
            if mode == "full content":
                mode = "focused excerpt"
                reason = "budget-limited after higher-priority files"

        remaining = max(0, remaining - char_cost)
        rendered.append(
            BudgetedFileContext(
                path=file.path,
                content_mode=mode,
                reason=reason,
                lines=selected,
                summary_only=not bool(selected),
            )
        )

    # Preserve workset ordering in the final prompt while retaining budget decisions.
    by_path = {item.path: item for item in rendered}
    return [by_path[file.path] for file in bundle.files if file.path in by_path]


def _priority(
    file: ContextBundleFile,
    task_lower: str,
    target_paths: set[str],
) -> tuple[int, int, int]:
    priority = getattr(file, "score", 0)
    if file.path in target_paths:
        priority += 80
    if _task_mentions_path(task_lower, file.path):
        priority += 60
    if getattr(file, "category", "") == "test" or _is_test_file(file.path):
        priority += 20 if any(t in task_lower for t in ("test", "tests", "spec", "specs")) else -10
    if _is_docs_or_config_file(file):
        priority -= 15
    if _is_infrastructure_file(file):
        priority -= 25
    return (priority, -getattr(file, "line_count", 0), -getattr(file, "char_count", 0))


def _focused_lines(file: ContextBundleFile, task_lower: str, limit: int) -> list[str]:
    available = [line for line in getattr(file, "excerpts", []) if line != OMIT_MARKER]
    if len(available) <= limit:
        return available

    terms = _task_terms(task_lower)
    selected: list[str] = []
    if terms:
        lowered_lines = [line.lower() for line in available]
        matched: set[int] = set()
        for idx, line in enumerate(lowered_lines):
            if any(term in line for term in terms):
                for near in range(max(0, idx - 4), min(len(available), idx + 5)):
                    matched.add(near)
        for idx in sorted(matched):
            selected.append(available[idx])
            if len(selected) >= limit:
                return selected

    head_count = min(limit, max(40, limit // 3))
    selected = available[:head_count]
    if len(selected) < limit:
        tail_count = min(limit - len(selected), 40)
        selected.extend(available[-tail_count:])
    return selected[:limit]


def _task_terms(task_lower: str) -> list[str]:
    return [
        term
        for term in task_lower.replace("/", " ").replace(".", " ").split()
        if len(term) > 3
    ]


def _task_mentions_path(task_lower: str, path: str) -> bool:
    lowered = path.lower()
    filename = lowered.rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0]
    return lowered in task_lower or filename in task_lower or stem in task_lower


def _is_test_file(path: str) -> bool:
    lowered = path.lower()
    return (
        lowered.startswith("tests/")
        or "/tests/" in lowered
        or lowered.startswith("test_")
        or "/test_" in lowered
        or lowered.endswith(("_test.py", "_spec.py", ".spec.py", ".test.py"))
        or "test" in lowered
    )


def _is_docs_or_config_file(file: ContextBundleFile) -> bool:
    lowered = file.path.lower()
    suffixes = (
        ".md",
        ".rst",
        ".txt",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".ini",
        ".cfg",
        ".lock",
    )
    return getattr(file, "category", "") in {
        "docs",
        "documentation",
        "config",
    } or lowered.endswith(suffixes)


def _is_infrastructure_file(file: ContextBundleFile) -> bool:
    lowered = file.path.lower()
    return (
        getattr(file, "category", "") in {"infra", "infrastructure", "build"}
        or lowered.startswith((".github/", "infra/", "deploy/", "deployment/"))
        or lowered.endswith(("dockerfile", "makefile"))
        or "dockerfile" in lowered
    )


# ---------------------------------------------------------------------------
# Implementation prompt target isolation
#
# Workset files != editable prompt files. A workset intentionally carries
# broader context than the model is allowed to edit (related DTOs, adjacent
# controllers, cross-module callers). Handing that same full, SEARCH/REPLACE-
# ready content to the model invites it to emit edits for files outside the
# approved editable target set — which Forge then has to reject after the
# fact. This section produces a deterministic three-way split so implementation
# prompts only ever hand out full content for approved editable targets.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImplementationPromptContext:
    """Editable vs. context-only vs. omitted split of a workset for one prompt.

    ``editable_files`` are the only files that receive full, budgeted,
    SEARCH/REPLACE-ready content (rendered with the "N| " line-number
    gutter). ``context_files`` are workset files relevant to understanding
    the change but not approved for editing — they get summaries, symbols,
    and dependency hints only, never verbatim source. ``omitted_files`` are
    workset files outside the approved target's module that are left out of
    the prompt entirely; they are retained here purely for diagnostics.
    """

    editable_files: list[BudgetedFileContext]
    context_files: list[ContextBundleFile]
    omitted_files: list[ContextBundleFile]
    approved_paths: set[str]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable diagnostic summary."""
        return {
            "editable_context_files": [f.path for f in self.editable_files],
            "context_only_files": [f.path for f in self.context_files],
            "omitted_files": [f.path for f in self.omitted_files],
            "approved_paths": sorted(self.approved_paths),
        }


def _normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/").lstrip("./")


def _module_root(path: str) -> str | None:
    """Return the top-level directory of ``path``, or ``None`` for a root-level file.

    Root-level files (e.g. ``README.md``) do not belong to any particular
    module, so they are never treated as "cross-module" on their own — only
    files that sit under a *different* top-level directory than the approved
    editable targets are.
    """
    parts = _normalize_path(path).split("/", 1)
    return parts[0] if len(parts) > 1 else None


def build_target_isolated_bundle(
    task: str,
    bundle: ContextBundle,
    editable_targets: EditableTargetSet,
    config: ContextBudgetConfig | None = None,
) -> ImplementationPromptContext:
    """Split ``bundle`` into editable / context-only / omitted files.

    Editable-file content budgeting (full content vs. focused excerpt) is
    computed over the editable subset only, so a large or highly-scored
    non-editable workset file can never consume the "full content" budget
    that an approved editable target needs.

    Non-editable files are classified by module: files that share a
    top-level directory with at least one approved editable target are
    "context" (relevant, summarized, non-editable); files under an entirely
    different top-level directory are "omitted" (left out of the prompt).
    When no approved target has a module root (e.g. a flat repository, or a
    task without a strong identifier where most workset files are already
    approved), nothing is treated as cross-module and everything left over
    is "context".
    """
    approved = editable_targets.allowed_paths()
    primary_roots = {
        root
        for target in editable_targets.targets
        if (root := _module_root(target.path)) is not None
    }

    editable_bundle_files = [f for f in bundle.files if _normalize_path(f.path) in approved]
    context_files: list[ContextBundleFile] = []
    omitted_files: list[ContextBundleFile] = []
    for f in bundle.files:
        if _normalize_path(f.path) in approved:
            continue
        root = _module_root(f.path)
        if primary_roots and root is not None and root not in primary_roots:
            omitted_files.append(f)
        else:
            context_files.append(f)

    editable_sub_bundle = ContextBundle(
        workset_name=bundle.workset_name,
        query=bundle.query,
        root=bundle.root,
        generated_at=bundle.generated_at,
        files=editable_bundle_files,
    )
    edit_plan = derive_edit_plan(task, editable_sub_bundle)
    editable_files = budget_implementation_context(task, editable_sub_bundle, edit_plan, config)

    return ImplementationPromptContext(
        editable_files=editable_files,
        context_files=context_files,
        omitted_files=omitted_files,
        approved_paths=approved,
    )
