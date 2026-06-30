"""Conservative edit-target planning for implementation prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from forge.context.bundle import ContextBundle

EditAction = Literal["modify", "create", "delete", "inspect"]


@dataclass(frozen=True)
class EditTarget:
    """A file the implementation prompt should prioritize."""

    file_path: str
    action: EditAction
    reason: str
    confidence: float


@dataclass(frozen=True)
class EditPlan:
    """Validated, workset-scoped edit targeting metadata."""

    targets: list[EditTarget]
    warnings: list[str]


def derive_edit_plan(task: str, bundle: ContextBundle) -> EditPlan:
    """Derive likely edit targets from deterministic workset metadata.

    This deliberately does not ask a model to introduce files.  The plan is
    only a context-prioritization hint: all targets are already in the workset.
    """
    task_lower = task.lower()
    task_mentions_tests = any(token in task_lower for token in ("test", "tests", "spec", "specs"))
    targets: list[EditTarget] = []

    for file in sorted(bundle.files, key=lambda item: getattr(item, "score", 0), reverse=True):
        if getattr(file, "error", None):
            continue

        confidence = min(0.95, 0.35 + (max(getattr(file, "score", 0), 0) / 100.0))
        reasons: list[str] = []
        action: EditAction = "modify"

        if getattr(file, "score", 0):
            reasons.append(f"workset score {getattr(file, 'score', 0)}")
        if getattr(file, "category", ""):
            reasons.append(f"category {getattr(file, 'category', '')}")
        if _task_mentions_path(task_lower, file.path):
            confidence = min(0.98, confidence + 0.25)
            reasons.append("task mentions filename/path")
        if getattr(file, "reasons", []):
            reason_blob = " ".join(getattr(file, "reasons", [])).lower()
            if "identifier" in reason_blob:
                confidence = min(0.98, confidence + 0.15)
                reasons.append("identifier match")
            if "relationship" in reason_blob:
                confidence = min(0.98, confidence + 0.1)
                reasons.append("relationship match")
        if _is_test_file(file.path):
            if task_mentions_tests:
                confidence = min(0.98, confidence + 0.2)
                reasons.append("task requests tests")
            elif getattr(file, "category", "") != "test":
                action = "inspect"
                confidence = max(0.2, confidence - 0.2)

        targets.append(
            EditTarget(
                file_path=file.path,
                action=action,
                reason=", ".join(reasons) or "included in workset",
                confidence=round(confidence, 2),
            )
        )

    return EditPlan(targets=targets[:8], warnings=[])


def render_edit_plan(plan: EditPlan) -> str:
    """Render edit targets as a compact prompt section."""
    if not plan.targets:
        return "(no deterministic edit targets)"
    lines = ["| File | Action | Confidence | Reason |", "| --- | --- | ---: | --- |"]
    for target in plan.targets:
        lines.append(
            f"| {target.file_path} | {target.action} | {target.confidence:.2f} | {target.reason} |"
        )
    if plan.warnings:
        lines.append("")
        lines.extend(f"- Warning: {warning}" for warning in plan.warnings)
    return "\n".join(lines)


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
