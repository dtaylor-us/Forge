"""Application service for generating reviewable implementation patches."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from forge.edit_targets import EditableTargetSet, select_editable_targets
from forge.execution import ExecutionService, ExecutionServiceError
from forge.execution.execution_prompt import (
    build_budgeted_numbered_file_details,
    build_implementation_prompt,
    build_repair_prompt,
    build_search_replace_prompt,
    build_search_replace_repair_prompt,
)
from forge.models.manager import ModelManager
from forge.patches import (
    Patch,
    apply_check_patch_content,
    realign_patch_hunk_headers,
    save_invalid_response,
    save_patch_content,
    validate_patch_content,
    verify_patch_context,
)
from forge.patches.service import inspect_patch
from forge.planning.planner import ImplementationPlan
from forge.srp import SearchReplaceResult, apply_blocks, parse_search_replace_blocks


@dataclass(frozen=True)
class ImplementationResult:
    """Result metadata for a generated implementation patch attempt."""

    task: str
    workset: str
    model: str
    status: str
    patch_path: Path | None
    valid: bool
    affected_files: list[str]
    validation_errors: list[str]
    patch_name: str | None
    show_target: str | None
    raw_response_path: Path | None = None
    test_warning: str | None = None
    repair_attempts_made: int = 0
    srp_failure_details: list[dict[str, Any]] | None = None
    editable_targets: EditableTargetSet | None = None
    rejected_files: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable result."""
        return {
            "task": self.task,
            "workset": self.workset,
            "model": self.model,
            "status": self.status,
            "patch_path": str(self.patch_path) if self.patch_path is not None else None,
            "patch_name": self.patch_name,
            "valid": self.valid,
            "affected_files": self.affected_files,
            "validation_errors": self.validation_errors,
            "raw_response_path": (
                str(self.raw_response_path) if self.raw_response_path is not None else None
            ),
            "next_command": (
                f"forge patch show {self.show_target}" if self.show_target is not None else None
            ),
            "test_warning": self.test_warning,
            "repair_attempts_made": self.repair_attempts_made,
            "srp_failure_details": self.srp_failure_details or [],
            "editable_targets": (
                self.editable_targets.to_dict() if self.editable_targets is not None else None
            ),
            "rejected_files": self.rejected_files or [],
        }


class ImplementationServiceError(Exception):
    """Raised when implementation patch generation cannot complete."""


class ImplementationService:
    """Generate reviewable patches without applying them."""

    def __init__(self, model_manager: ModelManager | None = None) -> None:
        self._model_manager = model_manager or ModelManager()
        self._execution_service = ExecutionService(self._model_manager)

    def implement(
        self,
        root: Path,
        task: str,
        workset: str,
        *,
        model: str | None = None,
        timeout_seconds: int | None = None,
        max_lines_per_file: int = 60,
        include_full: bool = True,
        output_path: Path | None = None,
        repair_attempts: int = 1,
        output_format: Literal["search_replace", "unified_diff"] = "search_replace",
        editable_targets: EditableTargetSet | None = None,
    ) -> ImplementationResult:
        """Generate and store a model-produced patch, with optional repair.

        ``output_format`` controls which strategy the model uses:
        - ``"search_replace"`` (default): Model produces SEARCH/REPLACE blocks; forge
          applies them in memory and generates the unified diff via difflib.  The model
          only needs to copy content verbatim — no line numbers required — which
          eliminates the main failure class of unified-diff generation.
        - ``"unified_diff"``: Legacy path.  Model produces a raw unified diff directly.
          Kept for fallback and comparison.

        ``include_full`` defaults to True: both strategies require the model to
        reproduce exact file content, so excerpted/truncated content (the default
        for browsing-oriented commands) is not appropriate here.
        """
        selected_model = model or self._model_manager.config().default_model
        request = self._execution_service.create_request(
            root,
            task,
            workset,
            model=selected_model,
            implementation_plan=_default_implementation_plan(task, workset, selected_model),
            max_lines_per_file=max_lines_per_file,
            include_full=include_full,
        )
        if request.context_bundle is None or request.implementation_plan is None:
            raise ExecutionServiceError("Execution context was not prepared.")

        editable_targets = editable_targets or select_editable_targets(task, request.context_bundle)

        if output_format == "search_replace":
            target_errors = _editable_target_errors(
                task, workset, request.context_bundle, editable_targets
            )
            if target_errors:
                return ImplementationResult(
                    task=task,
                    workset=workset,
                    model=selected_model,
                    status="rejected",
                    patch_path=None,
                    valid=False,
                    affected_files=[],
                    validation_errors=target_errors,
                    patch_name=None,
                    show_target=None,
                    editable_targets=editable_targets,
                )
            return self._implement_search_replace(
                root=root,
                task=task,
                workset=workset,
                request=request,
                selected_model=selected_model,
                model=model,
                timeout_seconds=timeout_seconds,
                output_path=output_path,
                repair_attempts=repair_attempts,
                editable_targets=editable_targets,
            )
        return self._implement_unified_diff(
            root=root,
            task=task,
            workset=workset,
            request=request,
            selected_model=selected_model,
            model=model,
            timeout_seconds=timeout_seconds,
            output_path=output_path,
            repair_attempts=repair_attempts,
        )

    # ------------------------------------------------------------------
    # Search/Replace path
    # ------------------------------------------------------------------

    def _implement_search_replace(
        self,
        root: Path,
        task: str,
        workset: str,
        request: Any,
        selected_model: str,
        model: str | None,
        timeout_seconds: int | None,
        output_path: Path | None,
        repair_attempts: int,
        editable_targets: EditableTargetSet,
    ) -> ImplementationResult:
        """Full search-replace pipeline: prompt → parse → apply → diff → validate."""
        prompt, test_warning = build_search_replace_prompt(
            task,
            request.context_bundle,
            request.implementation_plan,
            request.selected_model or selected_model,
            request.related_memory,
            editable_targets,
        )
        request.prompt = prompt

        response = self._model_manager.ask(
            prompt=prompt,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        current_model = response.model
        raw_response = _strip_markdown_fence(response.content)
        attempts_made = 0

        srp_result, rejected_files = _parse_and_apply_srp(
            root,
            raw_response,
            truncated=response.truncated,
            editable_targets=editable_targets,
        )
        file_details = _bundle_file_details(task, request.context_bundle)

        while not srp_result.valid and not rejected_files and attempts_made < repair_attempts:
            attempts_made += 1
            auth_excerpts = _srp_authoritative_excerpts(root, srp_result)
            repair_prompt = build_search_replace_repair_prompt(
                task=task,
                original_response=raw_response,
                failures=srp_result.errors,
                failure_details=srp_result.failure_details,
                file_details=file_details,
                authoritative_excerpts=auth_excerpts,
            )
            repair_response = self._model_manager.ask(
                prompt=repair_prompt,
                model=model,
                timeout_seconds=timeout_seconds,
            )
            raw_response = _strip_markdown_fence(repair_response.content)
            current_model = repair_response.model
            srp_result, rejected_files = _parse_and_apply_srp(
                root,
                raw_response,
                truncated=repair_response.truncated,
                editable_targets=editable_targets,
            )

        if srp_result.valid and srp_result.patch_content:
            # The SRP applier produced a clean unified diff — validate it
            # through the same pipeline as the legacy path.
            patch_content, _ = realign_patch_hunk_headers(root, srp_result.patch_content)
            valid, errors, affected_files = validate_patch_content(patch_content)
            apply_ok, apply_error = _apply_check_if_structurally_valid(root, patch_content, valid)
            if valid and apply_ok:
                patch = _save_valid_patch(
                    root, patch_content, output_path=output_path, task=task
                )
                return ImplementationResult(
                    task=task,
                    workset=workset,
                    model=current_model,
                    status="accepted",
                    patch_path=patch.path,
                    valid=patch.valid,
                    affected_files=patch.affected_files,
                    validation_errors=patch.validation_errors,
                    patch_name=patch.name,
                    show_target=_show_target(root, patch.path),
                    test_warning=test_warning,
                    repair_attempts_made=attempts_made,
                    editable_targets=editable_targets,
                )
            # SRP applied OK but the resulting diff is still invalid (edge case).
            # Fall through to rejected result below.
            if apply_error and apply_error not in errors:
                errors = [*errors, apply_error]
            invalid_path = save_invalid_response(
                root, patch_content, prefix=_artifact_slug(task)
            )
            return ImplementationResult(
                task=task,
                workset=workset,
                model=current_model,
                status="rejected",
                patch_path=None,
                valid=False,
                affected_files=affected_files,
                validation_errors=errors,
                patch_name=None,
                show_target=None,
                raw_response_path=invalid_path,
                test_warning=test_warning,
                repair_attempts_made=attempts_made,
                editable_targets=editable_targets,
            )

        # SRP itself failed (parse error or block not found).
        invalid_path = save_invalid_response(root, raw_response, prefix=_artifact_slug(task))
        return ImplementationResult(
            task=task,
            workset=workset,
            model=current_model,
            status="rejected",
            patch_path=None,
            valid=False,
            affected_files=[],
            validation_errors=srp_result.errors,
            patch_name=None,
            show_target=None,
            raw_response_path=invalid_path,
            test_warning=test_warning,
            repair_attempts_made=attempts_made,
            srp_failure_details=[detail.to_dict() for detail in srp_result.failure_details],
            editable_targets=editable_targets,
            rejected_files=rejected_files,
        )

    # ------------------------------------------------------------------
    # Unified-diff path (legacy)
    # ------------------------------------------------------------------

    def _implement_unified_diff(
        self,
        root: Path,
        task: str,
        workset: str,
        request: Any,
        selected_model: str,
        model: str | None,
        timeout_seconds: int | None,
        output_path: Path | None,
        repair_attempts: int,
    ) -> ImplementationResult:
        """Legacy unified-diff pipeline kept for fallback and comparison."""
        prompt, test_warning = build_implementation_prompt(
            task,
            request.context_bundle,
            request.implementation_plan,
            request.selected_model or selected_model,
            request.related_memory,
        )
        request.prompt = prompt

        response = self._model_manager.ask(
            prompt=prompt,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        current_content = _strip_markdown_fence(response.content)
        # Deterministically correct miscounted hunk starting positions before
        # validation. git apply --recount (applied by GitService) fixes hunk
        # line *counts*, but it cannot fix a wrong starting *position* (L in
        # @@ -L,N @@). This pass searches the real file for the unique location
        # where each hunk's context/removed block appears and rewrites the header
        # when exactly one match is found, eliminating that failure class without
        # touching content the model got right.
        current_content, _ = realign_patch_hunk_headers(root, current_content)
        current_model = response.model
        attempts_made = 0

        valid, errors, affected_files = validate_patch_content(current_content)
        apply_ok, apply_error = _apply_check_if_structurally_valid(root, current_content, valid)
        is_valid = valid and apply_ok
        context_mismatches = [] if is_valid else verify_patch_context(root, current_content)

        file_details = _bundle_file_details(task, request.context_bundle)
        while not is_valid and attempts_made < repair_attempts:
            attempts_made += 1
            targeted_excerpts = _targeted_disk_excerpts(root, context_mismatches)
            repair_prompt = build_repair_prompt(
                task=task,
                original_patch=current_content,
                structural_errors=errors,
                apply_check_error=apply_error,
                file_details=file_details,
                context_mismatches=context_mismatches,
                targeted_file_excerpts=targeted_excerpts,
            )
            repair_response = self._model_manager.ask(
                prompt=repair_prompt,
                model=model,
                timeout_seconds=timeout_seconds,
            )
            current_content = _strip_markdown_fence(repair_response.content)
            current_content, _ = realign_patch_hunk_headers(root, current_content)
            current_model = repair_response.model
            valid, errors, affected_files = validate_patch_content(current_content)
            apply_ok, apply_error = _apply_check_if_structurally_valid(
                root,
                current_content,
                valid,
            )
            is_valid = valid and apply_ok
            context_mismatches = [] if is_valid else verify_patch_context(root, current_content)

        if is_valid:
            patch = _save_valid_patch(root, current_content, output_path=output_path, task=task)
            return ImplementationResult(
                task=task,
                workset=workset,
                model=current_model,
                status="accepted",
                patch_path=patch.path,
                valid=patch.valid,
                affected_files=patch.affected_files,
                validation_errors=patch.validation_errors,
                patch_name=patch.name,
                show_target=_show_target(root, patch.path),
                test_warning=test_warning,
                repair_attempts_made=attempts_made,
            )

        if apply_error and apply_error not in errors:
            errors = [*errors, apply_error]
        if context_mismatches:
            # Surface the specific line-level diagnosis (patch expected X, file
            # actually has Y) on final failure, not just the raw, often-cryptic
            # `git apply` message (e.g. "corrupt patch at line 15"). This was
            # already computed to drive the repair prompt; previously it was
            # discarded once repair attempts ran out, leaving callers with
            # only the opaque git error.
            errors = [*errors, *[m for m in context_mismatches if m not in errors]]
        invalid_path = save_invalid_response(root, current_content, prefix=_artifact_slug(task))
        return ImplementationResult(
            task=task,
            workset=workset,
            model=current_model,
            status="rejected",
            patch_path=None,
            valid=False,
            affected_files=affected_files,
            validation_errors=errors,
            patch_name=None,
            show_target=None,
            raw_response_path=invalid_path,
            test_warning=test_warning,
            repair_attempts_made=attempts_made,
        )


def _parse_and_apply_srp(
    root: Path,
    raw_response: str,
    *,
    truncated: bool = False,
    editable_targets: EditableTargetSet | None = None,
) -> tuple[SearchReplaceResult, list[str]]:
    """Parse SEARCH/REPLACE blocks from ``raw_response`` and apply them to ``root``.

    When the provider reports the response was cut off by an output-length or
    context-window limit (``truncated``) and parsing finds zero blocks, the
    generic "no blocks found" error is replaced with a specific, actionable
    one — without this, a truncated response and a model that simply ignored
    the requested format look identical to the caller.
    """
    blocks = parse_search_replace_blocks(raw_response)
    rejected_files = _rejected_srp_files(blocks, editable_targets)
    if rejected_files:
        allowed = _format_approved_targets(editable_targets)
        errors = [
            "Model attempted to edit a file outside the approved target set:\n"
            + "\n".join(rejected_files)
            + "\nApproved editable targets:\n"
            + allowed
        ]
        return (
            SearchReplaceResult(
                blocks=blocks,
                applications=[],
                patch_content=None,
                valid=False,
                errors=errors,
                raw_response=raw_response,
                failure_details=[],
            ),
            rejected_files,
        )
    result = apply_blocks(root, blocks)
    errors = result.errors
    if truncated and not blocks:
        errors = [
            "Model response was truncated (hit the configured output-length or "
            "context-window limit) before any complete SEARCH/REPLACE block was "
            "produced. Increase providers.<provider>.max_tokens (and, for Ollama, "
            "context_window) in ~/.forge/config.yaml.",
            *errors,
        ]
    # Preserve the raw response so callers can save it as an artifact on failure.
    return (
        SearchReplaceResult(
            blocks=result.blocks,
            applications=result.applications,
            patch_content=result.patch_content,
            valid=result.valid,
            errors=errors,
            raw_response=raw_response,
            failure_details=result.failure_details,
        ),
        [],
    )


def _editable_target_errors(
    task: str,
    workset: str,
    bundle: Any,
    editable_targets: EditableTargetSet,
) -> list[str]:
    if editable_targets.missing_required:
        missing = ", ".join(editable_targets.missing_required)
        return [
            f"Required edit target not found in workset: {missing}\n"
            "This usually means workset selection failed.\n"
            "Run:\n"
            f'forge workset suggest "{task}"\n'
            f'forge workset create {workset} --query "{task}"'
        ]
    if not editable_targets.targets:
        files = "\n".join(f"- {getattr(file, 'path', '')}" for file in getattr(bundle, "files", []))
        return [
            "No editable targets were found for this task.\n"
            "This usually means the workset did not contain the target file.\n"
            f"Task:\n{task}\n"
            f"Workset files:\n{files or '(none)'}"
        ]
    return []


def _rejected_srp_files(blocks: list[Any], editable_targets: EditableTargetSet | None) -> list[str]:
    if editable_targets is None:
        return []
    allowed = editable_targets.allowed_paths()
    rejected: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        path = block.file_path.strip().replace("\\", "/").lstrip("./")
        if path not in allowed and path not in seen:
            seen.add(path)
            rejected.append(path)
    return rejected


def _format_approved_targets(editable_targets: EditableTargetSet | None) -> str:
    if editable_targets is None or not editable_targets.targets:
        return "- (none)"
    return "\n".join(
        f"- {target.path} ({target.confidence}: {target.reason})"
        for target in editable_targets.targets
    )


def _srp_authoritative_excerpts(root: Path, srp_result: SearchReplaceResult) -> str:
    """Produce disk-fresh excerpts for each file that had a failed SRP block.

    Works analogously to ``_targeted_disk_excerpts`` for the unified-diff path.
    For each failed application we extract a window of file content around the
    region the SEARCH block was targeting (approximated by searching for the
    first line of the SEARCH string in the file, or falling back to lines 1-40).
    """
    parts: list[str] = []
    context_lines = 20
    for app in srp_result.applications:
        if app.applied:
            continue
        file_path = app.block.file_path
        abs_path = root / file_path
        try:
            file_text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_lines = file_text.splitlines()
        n = len(file_lines)

        # Try to locate roughly where the SEARCH content should be by finding
        # the first non-blank line of the search string in the file.
        approx_line = 0
        first_search_line = next(
            (ln.strip() for ln in app.block.search.splitlines() if ln.strip()), ""
        )
        if first_search_line:
            for idx, fl in enumerate(file_lines):
                if fl.strip() == first_search_line:
                    approx_line = idx
                    break

        start = max(0, approx_line - context_lines)
        end = min(n, approx_line + context_lines + 1)
        snippet = []
        for idx in range(start, end):
            marker = ">>>" if idx == approx_line else "   "
            snippet.append(f"{idx + 1:>5}{marker}| {file_lines[idx]}")

        header = f"### {file_path} (lines {start + 1}–{end})"
        parts.append(header + "\n```\n" + "\n".join(snippet) + "\n```")

    return "\n\n".join(parts)


def _strip_markdown_fence(content: str) -> str:
    """Extract raw diff from a markdown code fence if the model wrapped it."""
    stripped = content.strip()
    # Match ```diff, ```patch, or plain ``` opening fence
    match = re.match(r"^```(?:diff|patch)?\s*\n(.*?)```\s*$", stripped, re.DOTALL)
    if match:
        return match.group(1)
    return content


def _save_valid_patch(
    root: Path,
    content: str,
    *,
    output_path: Path | None,
    task: str,
) -> Patch:
    if output_path is None:
        return save_patch_content(root, content, prefix=_artifact_slug(task))
    path = output_path.expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    except OSError as exc:
        raise ImplementationServiceError(f"Unable to write patch to {path}: {exc}") from exc
    return inspect_patch(path)


def _default_implementation_plan(task: str, workset: str, model: str) -> ImplementationPlan:
    return ImplementationPlan(
        task=task,
        workset_name=workset,
        model=model,
        generated_at=datetime.now(tz=UTC),
        content=(
            "No saved implementation plan was provided. Generate the smallest reviewable "
            "patch that satisfies the task using the supplied workset context."
        ),
    )


def _show_target(root: Path, path: Path) -> str:
    default_patch_dir = root / ".forge" / "patches"
    try:
        if path.parent.resolve() == default_patch_dir.resolve():
            return path.name
    except OSError:
        pass
    return str(path)


def _apply_check_if_structurally_valid(
    root: Path,
    content: str,
    structurally_valid: bool,
) -> tuple[bool, str]:
    if not structurally_valid:
        return False, "Structural validation failed"
    return apply_check_patch_content(root, content)


def _bundle_file_details(task: str, bundle: Any) -> str:
    """Extract detailed, line-numbered file context from a bundle for repair prompts.

    Uses the same "N| " gutter rendering as the initial implementation
    prompt (see ``build_numbered_file_details``) so the model has line-number
    ground truth on repair attempts too, instead of repeating the same
    miscounted hunk header it produced the first time.
    """
    return build_budgeted_numbered_file_details(task, bundle)


def _targeted_disk_excerpts(
    root: Path,
    context_mismatches: list[str],
    context_lines: int = 20,
) -> str:
    """Extract actual file lines around each mismatch location, read fresh from disk.

    The context bundle used for ``file_details`` may be budget-truncated (e.g. only
    lines 1-60 visible) when the workset is large.  A model that cannot see line 165
    in ``file_details`` will hallucinate what the file looks like there and repeat the
    same wrong context across all repair attempts.

    This reads the source file directly from disk for each mismatch and returns a
    ``context_lines``-wide window centred on the mismatched line, numbered with the
    same "N| " gutter the model already uses to produce correct ``@@ -L,N @@`` headers.
    It is safe to call when ``context_mismatches`` is empty (returns an empty string).
    """
    import re as _re

    _MISMATCH_RE = _re.compile(r"^(.+?):(\d+): patch context does not match", _re.MULTILINE)

    # Collect unique (file, line) pairs from the mismatch report.
    seen: set[tuple[str, int]] = set()
    locations: list[tuple[str, int]] = []
    for mismatch in context_mismatches:
        for m in _MISMATCH_RE.finditer(mismatch):
            key = (m.group(1), int(m.group(2)))
            if key not in seen:
                seen.add(key)
                locations.append(key)

    if not locations:
        return ""

    parts: list[str] = []
    for rel_path, line_no in locations:
        abs_path = root / rel_path
        try:
            file_lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        start = max(0, line_no - context_lines - 1)
        end = min(len(file_lines), line_no + context_lines)
        snippet_lines = []
        for idx in range(start, end):
            marker = ">>>" if idx + 1 == line_no else "   "
            snippet_lines.append(f"{idx + 1:>5}{marker}| {file_lines[idx]}")

        header = f"### {rel_path} (lines {start + 1}–{end}, >>> marks the mismatched line)"
        parts.append(header + "\n```\n" + "\n".join(snippet_lines) + "\n```")

    return "\n\n".join(parts)


def _artifact_slug(task: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in task)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:60] or "implement"
