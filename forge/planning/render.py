"""Render ImplementationPlan objects for display."""

from __future__ import annotations

import json

from forge.planning.planner import ImplementationPlan


def render_plan_text(plan: ImplementationPlan) -> str:
    """Return the raw Markdown content of the plan."""
    return plan.content


def render_plan_json(plan: ImplementationPlan) -> str:
    """Return the plan as a JSON string."""
    data = {
        "task": plan.task,
        "workset_name": plan.workset_name,
        "model": plan.model,
        "generated_at": plan.generated_at.isoformat(),
        "content": plan.content,
        "saved_path": str(plan.saved_path) if plan.saved_path else None,
    }
    return json.dumps(data, indent=2)
