"""Policy application service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forge.git.service import GitService
from forge.patches import validate_patch_file
from forge.policies.service import evaluate_policy, show_policy
from forge.project.paths import ForgePaths


class PolicyServiceError(Exception):
    """Raised when policy infrastructure fails."""


def show(root: Path) -> dict[str, Any]:
    """Return the active policy as a dict."""
    return show_policy(root)


def check(
    root: Path,
    patch_name_or_path: str,
    verification_path: str | None = None,
) -> dict[str, Any]:
    """Evaluate a patch against the active policy. Returns structured result."""
    patch_meta = validate_patch_file(root, patch_name_or_path).to_dict()

    git_svc = GitService(cwd=root)
    git_status = git_svc.status().to_dict()

    verification_report = _load_verification_report(root, verification_path)

    evaluation = evaluate_policy(root, patch_meta, git_status, verification_report)
    return {
        "patch": patch_meta["name"],
        "evaluation": evaluation.to_dict(),
        "verification_report_used": (
            str(verification_path) if verification_path else _latest_report_path(root)
        ),
    }


def _load_verification_report(root: Path, path_or_name: str | None) -> dict[str, Any] | None:
    report_path = _resolve_report_path(root, path_or_name)
    if report_path is None:
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_report_path(root: Path, path_or_name: str | None) -> Path | None:
    if path_or_name is not None:
        candidate = Path(path_or_name).expanduser()
        if candidate.exists():
            return candidate
        saved = ForgePaths.from_root(root).verifications_dir / path_or_name
        if saved.exists():
            return saved
        return None
    return _latest_report(root)


def _latest_report(root: Path) -> Path | None:
    verif_dir = ForgePaths.from_root(root).verifications_dir
    if not verif_dir.exists():
        return None
    reports = sorted(
        (p for p in verif_dir.iterdir() if p.is_file() and p.suffix == ".json"),
        key=lambda p: p.name,
    )
    return reports[-1] if reports else None


def _latest_report_path(root: Path) -> str | None:
    p = _latest_report(root)
    return str(p) if p else None
