"""Verification execution pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from forge.verification.detector import detect_verification_strategy
from forge.verification.models import VerificationStep, VerificationTool
from forge.verification.report import (
    VerificationArtifactMetadata,
    VerificationReport,
    VerificationStatus,
    VerificationStepResult,
)
from forge.verification.runner import CommandRunner

DEFAULT_TIMEOUT_SECONDS = 300
STEP_ORDER = {"formatter": 0, "linter": 1, "build": 2, "tests": 3}


class VerificationExecutionError(Exception):
    """Raised when verification cannot produce a report."""


class VerificationExecutor:
    """Execute detected verification strategy steps."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()

    def execute(
        self,
        root: Path,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        metadata: dict[str, str | None] | None = None,
    ) -> VerificationReport:
        """Execute repository verification and return a structured report."""
        if not root.exists() or not root.is_dir():
            raise VerificationExecutionError(f"Repository root does not exist: {root}")

        started = perf_counter()
        strategy = detect_verification_strategy(root)
        steps = [
            self._execute_step(root, step, timeout=timeout)
            for step in sorted(strategy.steps, key=lambda item: STEP_ORDER.get(item.kind, 99))
        ]
        duration = perf_counter() - started
        summary = _summary(steps)
        overall_status = (
            VerificationStatus.pass_
            if steps and all(step.status == VerificationStatus.pass_ for step in steps)
            else VerificationStatus.fail
        )
        if not steps:
            overall_status = VerificationStatus.fail
            summary["reason"] = "No deterministic verification steps were detected."

        return VerificationReport(
            repository={"root": str(root), "name": root.name},
            strategy=strategy,
            steps=steps,
            summary=summary,
            duration=duration,
            overall_status=overall_status,
            recommendations=_build_recommendations(steps),
            artifact=VerificationArtifactMetadata(),
            metadata={key: value for key, value in (metadata or {}).items() if value},
        )

    def _execute_step(
        self,
        root: Path,
        step: VerificationStep,
        *,
        timeout: float,
    ) -> VerificationStepResult:
        result = self.runner.run(step.command, root, timeout=timeout)
        status = VerificationStatus.pass_ if result.exit_code == 0 else VerificationStatus.fail
        if result.exception and not result.timed_out:
            status = VerificationStatus.error
        return VerificationStepResult(
            tool=_tool_value(step.tool),
            command=result.command,
            working_directory=result.working_directory,
            started_at=result.started_at,
            completed_at=result.completed_at,
            duration=result.duration,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            status=status,
            timed_out=result.timed_out,
            exception=result.exception,
            kind=step.kind,
            name=step.name,
        )


def _summary(steps: list[VerificationStepResult]) -> dict[str, object]:
    counts = {
        "total": len(steps),
        "passed": sum(step.status == VerificationStatus.pass_ for step in steps),
        "failed": sum(step.status == VerificationStatus.fail for step in steps),
        "errors": sum(step.status == VerificationStatus.error for step in steps),
        "timed_out": sum(step.timed_out for step in steps),
    }
    by_kind = {
        kind: next((step.status.value for step in steps if step.kind == kind), "skipped")
        for kind in ("formatter", "linter", "build", "tests")
    }
    return {"counts": counts, "by_kind": by_kind}


def _build_recommendations(steps: list[VerificationStepResult]) -> list[str]:
    """Generate deterministic recommendations for failed verification steps."""
    recommendations: list[str] = []
    for step in steps:
        if step.status in (VerificationStatus.fail, VerificationStatus.error):
            tool = step.tool.lower() if step.tool else ""
            kind = step.kind or ""
            if tool == "black" or (kind == "formatter" and "black" in (step.command or "")):
                recommendations.append("Run black . to auto-format source files.")
            elif tool == "ruff" or (kind == "linter" and "ruff" in (step.command or "")):
                recommendations.append(
                    "Run ruff check . to see lint errors, or ruff check --fix . to auto-fix."
                )
            elif tool == "pytest" or (kind == "tests" and "pytest" in (step.command or "")):
                recommendations.append(
                    "Run pytest -v to see failing tests."
                    " Check imports and PYTHONPATH if tests fail to collect."
                )
            elif kind == "tests" and "npm" in (step.command or ""):
                recommendations.append(
                    "Run npm test to see failing tests. Inspect test output for assertion failures."
                )
            elif kind == "build":
                recommendations.append(
                    "Inspect build output above. Check for missing dependencies or syntax errors."
                )
            elif step.status == VerificationStatus.error and step.exception:
                if "not found" in (step.exception or "").lower():
                    recommendations.append(
                        f"Tool '{step.tool}' was not found."
                        " Install it or update the verification strategy."
                    )
                else:
                    recommendations.append(
                        f"Step '{step.name or step.tool}' raised an error: {step.exception}"
                    )
    return recommendations


def _tool_value(tool: VerificationTool | str) -> str:
    return tool.value if isinstance(tool, VerificationTool) else str(tool)


def timestamp_slug() -> str:
    """Return a UTC timestamp suitable for artifact filenames."""
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
