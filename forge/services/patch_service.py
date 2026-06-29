"""Patch application service for saved patch inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.git.service import GitService, GitServiceError
from forge.patches import list_patches, read_patch, validate_patch_file
from forge.patches.service import resolve_patch_path


def list_all(root: Path) -> list[dict[str, Any]]:
    """Return metadata for saved patches."""
    return [patch.to_dict() for patch in list_patches(root)]


def show(root: Path, patch_name: str) -> dict[str, Any]:
    """Return saved patch metadata and content."""
    patch = validate_patch_file(root, patch_name)
    data = patch.to_dict()
    data["content"] = read_patch(root, patch_name)
    return data


def validate(root: Path, patch_name: str) -> dict[str, Any]:
    """Validate a saved patch by name or direct path, including git apply --check."""
    patch = validate_patch_file(root, patch_name)
    data = patch.to_dict()
    structural_valid = patch.valid

    apply_check_valid: bool | None = None
    apply_check_error: str | None = None

    if structural_valid:
        git_svc = GitService(cwd=root)
        if git_svc.is_git_repository():
            try:
                patch_path = resolve_patch_path(root, patch_name)
                git_svc.apply_check(patch_path)
                apply_check_valid = True
            except GitServiceError as exc:
                apply_check_valid = False
                apply_check_error = str(exc)

    overall_valid = structural_valid and (apply_check_valid is not False)
    errors = list(patch.validation_errors)
    if apply_check_error:
        errors.append(f"git apply --check failed: {apply_check_error}")

    suggestions: list[str] = []
    if not overall_valid:
        suggestions.append("Re-run forge implement to regenerate the patch.")
        suggestions.append(f"Inspect the patch with: forge patch show {patch_name}")
        suggestions.append("Ask the model to regenerate a proper unified diff.")

    data["valid"] = overall_valid
    data["structural_valid"] = structural_valid
    data["apply_check_valid"] = apply_check_valid
    data["validation_errors"] = errors
    data["suggestions"] = suggestions
    return data
