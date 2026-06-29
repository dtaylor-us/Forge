"""Persistence for verification report artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from forge.artifacts.metadata import artifact_id, relative_to_root
from forge.artifacts.models import ArtifactType
from forge.project.paths import ForgePaths
from forge.verification.executor import timestamp_slug
from forge.verification.report import VerificationArtifactMetadata, VerificationReport


def verification_dir(root: Path) -> Path:
    """Return the project-local verification artifact directory."""
    return ForgePaths.from_root(root).verifications_dir


def ensure_verification_dir(root: Path) -> Path:
    """Create and return .forge/verifications under root."""
    directory = verification_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def register_report(
    root: Path,
    report: VerificationReport,
    *,
    output_path: Path | None = None,
) -> VerificationReport:
    """Persist a verification report and return it with artifact metadata."""
    path = output_path.expanduser() if output_path else _unique_report_path(root)
    if not path.is_absolute():
        path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    relative_path = relative_to_root(path, root)
    artifact = VerificationArtifactMetadata(
        path=path,
        relative_path=relative_path,
        artifact_id=artifact_id(ArtifactType.verification, relative_path, path.stem),
    )
    persisted = report.with_artifact(artifact)
    path.write_text(
        json.dumps(persisted.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return persisted


def _unique_report_path(root: Path) -> Path:
    directory = ensure_verification_dir(root)
    candidate = directory / f"verification-{timestamp_slug()}.json"
    counter = 2
    while candidate.exists():
        candidate = directory / f"verification-{timestamp_slug()}-{counter}.json"
        counter += 1
    return candidate
