"""Environment diagnostics."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass

from forge.config.manager import ForgeConfig
from forge.models.ollama import OllamaProvider


@dataclass(frozen=True)
class CheckResult:
    """Result from a diagnostic check."""

    name: str
    ok: bool
    detail: str
    required: bool = True


def run_doctor(config: ForgeConfig) -> list[CheckResult]:
    """Run Phase 1 environment checks."""
    return [
        _python_check(),
        _command_check("Git", "git", ["git", "--version"]),
        _command_check("ripgrep", "rg", ["rg", "--version"]),
        _command_check("Docker", "docker", ["docker", "--version"]),
        _java_check(),
        _ollama_check(config),
    ]


def _python_check() -> CheckResult:
    version = sys.version_info
    ok = version >= (3, 12)
    detail = platform.python_version()
    return CheckResult("Python >= 3.12", ok, detail)


def _command_check(name: str, executable: str, command: list[str]) -> CheckResult:
    path = shutil.which(executable)
    if not path:
        return CheckResult(name, False, f"{executable} not found")
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult(name, False, str(exc))
    output = (completed.stdout or completed.stderr).strip().splitlines()
    detail = output[0] if output else path
    return CheckResult(name, completed.returncode == 0, detail)


def _java_check() -> CheckResult:
    path = shutil.which("java")
    if not path:
        return CheckResult("Java", True, "not installed (optional)", required=False)
    try:
        completed = subprocess.run(
            ["java", "-version"], check=False, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult("Java", False, str(exc), required=False)
    output = (completed.stderr or completed.stdout).strip().splitlines()
    detail = output[0] if output else path
    return CheckResult("Java", completed.returncode == 0, detail, required=False)


def _ollama_check(config: ForgeConfig) -> CheckResult:
    endpoint = "http://localhost:11434"
    provider_config = config.providers.get("ollama")
    if provider_config and provider_config.endpoint:
        endpoint = provider_config.endpoint
    provider = OllamaProvider(endpoint)
    ok = provider.is_running()
    detail = f"responding at {endpoint}" if ok else f"not responding at {endpoint}"
    return CheckResult("Ollama", ok, detail)
