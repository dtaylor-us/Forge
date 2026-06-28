"""Save implementation plans to .forge/plans/."""

from __future__ import annotations

from pathlib import Path

from forge.planning.planner import ImplementationPlan

_PLANS_SUBDIR = "plans"


def plans_dir(project_forge_dir: Path) -> Path:
    """Return the .forge/plans directory."""
    return project_forge_dir / _PLANS_SUBDIR


def save_plan(plan: ImplementationPlan, project_forge_dir: Path) -> Path:
    """Write a plan to .forge/plans/<workset>-<timestamp>.md. Returns the path."""
    d = plans_dir(project_forge_dir)
    d.mkdir(parents=True, exist_ok=True)
    ts = plan.generated_at.strftime("%Y%m%dT%H%M%S")
    filename = f"{plan.workset_name}-{ts}.md"
    dest = d / filename
    dest.write_text(plan.content, encoding="utf-8")
    return dest
