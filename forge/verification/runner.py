"""Reusable command runner for engineering workflows."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter


@dataclass(frozen=True)
class CommandResult:
    """Captured result of a command execution."""

    command: str
    working_directory: Path
    started_at: str
    completed_at: str
    duration: float
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    exception: str | None = None


class CommandRunner:
    """Execute commands while capturing evidence for reports."""

    def run(self, command: str, working_directory: Path, *, timeout: float) -> CommandResult:
        """Run a command and return a captured result."""
        started_at = _now()
        started = perf_counter()
        stdout = ""
        stderr = ""
        exit_code: int | None = None
        timed_out = False
        exception: str | None = None
        try:
            completed = subprocess.run(
                shlex.split(command),
                cwd=working_directory,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = _decode_output(exc.stdout)
            stderr = _decode_output(exc.stderr)
            exit_code = None
            exception = f"Command timed out after {timeout:g} seconds."
        except Exception as exc:  # noqa: BLE001 - runner must record infrastructure failures.
            exception = f"{type(exc).__name__}: {exc}"
            exit_code = None
        completed_at = _now()
        return CommandResult(
            command=command,
            working_directory=working_directory,
            started_at=started_at,
            completed_at=completed_at,
            duration=perf_counter() - started,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            exception=exception,
        )


def _decode_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")
