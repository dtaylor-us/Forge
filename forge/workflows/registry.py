"""Read-oriented registry for workflow runs persisted under .forge/workflows/."""

from __future__ import annotations

import json
from pathlib import Path

from forge.workflows.models import WorkflowRun, WorkflowTemplate


class WorkflowRegistry:
    """Read and write workflow run records for a project root."""

    def __init__(self, workflows_dir: Path) -> None:
        self._dir = workflows_dir

    @classmethod
    def from_root(cls, root: Path) -> WorkflowRegistry:
        from forge.project.paths import ForgePaths

        return cls(ForgePaths.from_root(root).workflows_dir)

    def save(self, run: WorkflowRun) -> Path:
        """Persist a workflow run and return its file path."""
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{run.id}.json"
        path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
        return path

    def load(self, run_id: str) -> dict | None:
        path = self._dir / f"{run_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def list_runs(
        self,
        *,
        template: WorkflowTemplate | None = None,
    ) -> list[dict]:
        """Return workflow run summaries, newest first."""
        if not self._dir.exists():
            return []
        runs = []
        for p in sorted(self._dir.glob("*.json"), key=lambda f: f.name, reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if template is not None and data.get("template") != template.value:
                continue
            runs.append(data)
        return runs
