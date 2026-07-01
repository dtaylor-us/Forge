"""Build Engineering Execution prompts from prepared orchestration inputs."""

from __future__ import annotations

from typing import Any

from forge.context.bundle import ContextBundle, ContextBundleFile
from forge.context.excerpt import OMIT_MARKER
from forge.edit_targets import EditableTargetSet, select_editable_targets
from forge.execution.context_budget import (
    BudgetedFileContext,
    budget_implementation_context,
    build_target_isolated_bundle,
)
from forge.execution.edit_plan import derive_edit_plan, render_edit_plan
from forge.memory.search import MemorySearchResult
from forge.planning.planner import ImplementationPlan
from forge.planning.prompts import build_context_sections, build_memory_section

_EXECUTION_SYSTEM_INSTRUCTIONS = """\
You are a senior software engineer preparing for Engineering Execution.

STRICT RULES:
- Do NOT generate code patches or diffs.
- Do NOT claim any files have been modified.
- Do NOT modify any files.
- Do NOT invoke git.
- Reason only from the task, workset context, engineering memory, and implementation plan.
- Preserve human control: describe intended execution inputs and constraints, not actions taken.
- Keep provider-specific assumptions out of the response.
- Leave room for future patch generation, validation, review, application, verification, and repair.

Output format: Markdown with the exact section headings specified in the prompt.
"""

_EXECUTION_TEMPLATE = """\
{system_instructions}

---

# Execution Request

## Task
{task}

## Selected Model
{model}

## Workset
Name: {workset_name}
Query: {query}
Root: {root}
Generated: {generated_at}

## Workset Files Summary

| File | Category | Score | Lines | Symbols |
| --- | --- | ---: | ---: | --- |
{file_table_rows}

## Detailed File Context

{file_details}

## Implementation Plan

{implementation_plan}

---

# Output Required

Produce an execution readiness brief in exactly this Markdown structure:

```markdown
# Forge Execution Readiness

## Task

## Workset Used

## Plan Used

## Execution Inputs

## Deterministic Constraints

## Human Review Gates

## Future Patch Generation Inputs

## Verification Expectations

## Repair Hooks

## Open Questions Or Blockers
```

At the end of the brief, include this footer verbatim:

---
*This is an execution preparation request only. No files were modified.*
*Workset used: {workset_name}. Model: {{model_placeholder}}.*
"""

_IMPLEMENTATION_SYSTEM_INSTRUCTIONS = """\
You are a senior software engineer generating a human-reviewable patch.

STRICT OUTPUT CONTRACT:
- Return only a raw unified diff.
- Do not use Markdown fences.
- Do not include explanations, summaries, prefaces, or trailing commentary.
- Prefer files from the workset.
- Do not invent files unless necessary.
- Preserve existing architecture and style.
- Do not include secrets.
- Do not perform destructive changes.
- Include valid hunk markers with correct line counts.
- Use paths relative to the repository root.

CRITICAL DIFF RULES:
- For EXISTING files (listed in the workset context below), NEVER use a new-file diff
  from /dev/null. Use standard unified diff hunks showing the exact lines changed.
- Only use /dev/null in --- header when creating a file that does NOT currently exist.
- Hunk line counts in @@ -L,N +L,N @@ markers MUST be accurate. Count carefully.
- The "Detailed File Context" section below prefixes each file line with a
  "N| " line-number gutter (e.g. "142| def foo():"). This gutter exists so
  you can read off the correct starting line number and line count for each
  hunk instead of counting lines by eye. The gutter is NOT part of the file.
  Never copy "N| " into a diff line — every context/added/removed line in
  your output must start with exactly one of ' ', '+', '-' followed by the
  real source text, with no line-number prefix.
- The output must pass: git apply --check
"""

_IMPLEMENTATION_TEMPLATE = """\
{system_instructions}

---

# Task
{task}

# Selected Model
{model}

# Workset
Name: {workset_name}
Query: {query}
Root: {root}
Generated: {generated_at}

# Workset Files (ALL EXISTING in repository — do NOT use /dev/null for these)

| File | Category | Score | Lines | Symbols |
| --- | --- | ---: | ---: | --- |
{file_table_rows}

# Detailed File Context

{file_details}

# Edit Targeting Plan

{edit_plan}

# Implementation Plan Or Notes

{implementation_plan}

---

# Final Response Requirements

Return only a raw unified diff.
No Markdown fences.
No explanations.
Use diff headers and valid hunk markers.
All files in the Workset Files table ALREADY EXIST — use normal unified diff hunks,
never /dev/null for them.
Hunk counts in @@ markers must be exact. Use the "N| " line-number gutter in the
Detailed File Context section to compute them — do not include the gutter itself
in the diff.
"""

_TEST_GUIDANCE = """\

## Test File Requirement

The task explicitly requests tests. The Workset Files table above includes test files.
You MUST include changes to those test files in your patch.
Do not return a patch that only modifies source files when the task requests tests.
"""

_TEST_MISSING_NOTE = """\

## Test File Warning

The task requests tests, but no test files are present in this workset.
The patch will not include test changes unless test files are added to the workset.
"""


def build_execution_prompt(
    task: str,
    bundle: ContextBundle,
    implementation_plan: ImplementationPlan,
    model: str,
    memory_context: list[MemorySearchResult] | None = None,
) -> str:
    """Construct an execution preparation prompt without invoking a provider."""
    file_table_rows, file_details = build_context_sections(bundle)
    raw = _EXECUTION_TEMPLATE.format(
        system_instructions=_EXECUTION_SYSTEM_INSTRUCTIONS,
        task=task,
        model=model,
        workset_name=bundle.workset_name,
        query=bundle.query,
        root=bundle.root,
        generated_at=bundle.generated_at,
        file_table_rows=file_table_rows,
        file_details=file_details,
        implementation_plan=implementation_plan.content,
    )
    result = raw.replace("{model_placeholder}", model)
    if memory_context:
        result = (
            result
            + "\n\n"
            + build_memory_section(
                memory_context,
                guidance="Use them to preserve continuity and avoid repeating prior mistakes.",
            )
        )
    return result


def build_numbered_file_details(bundle: ContextBundle) -> str:
    """Render file details with a "N| " line-number gutter for diff-generation prompts.

    Diff generation requires the model to produce accurate
    `@@ -L,N +L,N @@` hunk headers. The plain rendering used by planning
    prompts (`build_context_sections`) shows file content as a bare fenced
    block with no line numbers, which forces the model to count lines by
    eye — a reliable source of unparseable ("corrupt patch") hunks on
    anything past a trivial file. This renders the same verbatim content
    with a line-number gutter so the model has ground truth to read hunk
    positions from, instead of guessing.

    Numbering assumes contiguous coverage starting at line 1, which holds
    for the include_full bundles used by patch generation: `extract_excerpts`
    returns the whole file with at most one trailing OMIT_MARKER (for files
    over the line cap), never a mid-file gap. It is not used for excerpted/
    sampled bundles, where a mid-file OMIT_MARKER would make the running
    count wrong.
    """
    parts: list[str] = []
    for f in bundle.files:
        section: list[str] = [f"### {f.path}"]
        if f.error:
            section.append(f"**Error:** {f.error}")
            parts.append("\n".join(section))
            continue

        if f.summary:
            section.append("**Summary:** " + " | ".join(f.summary[:5]))
        if f.symbols:
            section.append("**Symbols:** " + ", ".join(f.symbols[:10]))
        if f.dependency_hints:
            section.append("**Dependencies:** " + "; ".join(f.dependency_hints[:8]))
        if f.excerpts:
            section.append(
                "**File Content (verbatim from disk, with a 'N| ' line-number gutter "
                "for your reference only — the gutter is NOT part of the file and must "
                "NEVER appear in your diff output; use it solely to compute correct "
                "'@@ -L,N +L,N @@' hunk headers; preserve indentation and whitespace "
                "after the gutter exactly):**"
            )
            section.append(_render_numbered_excerpt_blocks(f.excerpts))
        parts.append("\n".join(section))
    return "\n\n".join(parts)


def build_budgeted_numbered_file_details(task: str, bundle: ContextBundle) -> str:
    """Render implementation context under a deterministic prompt budget."""
    edit_plan = derive_edit_plan(task, bundle)
    budgeted = {item.path: item for item in budget_implementation_context(task, bundle, edit_plan)}
    parts: list[str] = []
    for f in bundle.files:
        section: list[str] = [f"### {f.path}"]
        decision = budgeted.get(f.path)
        if decision is not None:
            section.append(f"Content mode: {decision.content_mode}")
            section.append(f"Reason: {decision.reason}")
        if f.error:
            section.append(f"**Error:** {f.error}")
            parts.append("\n".join(section))
            continue

        if f.summary:
            section.append("**Summary:** " + " | ".join(f.summary[:5]))
        if f.symbols:
            section.append("**Symbols:** " + ", ".join(f.symbols[:10]))
        if f.dependency_hints:
            section.append("**Dependencies:** " + "; ".join(f.dependency_hints[:8]))
        selected_lines = decision.lines if decision is not None else f.excerpts
        if selected_lines:
            section.append(
                "**File Content (verbatim from disk, with a 'N| ' line-number gutter "
                "for your reference only — the gutter is NOT part of the file; preserve "
                "indentation and whitespace after the gutter exactly):**"
            )
            section.append(_render_numbered_excerpt_blocks(selected_lines))
        elif decision is not None:
            section.append("**File Content:** omitted by implementation context budget.")
        parts.append("\n".join(section))
    return "\n\n".join(parts)


def _render_numbered_excerpt_blocks(excerpts: list[str]) -> str:
    """Render excerpt lines with a 1-based line-number gutter, preserving omit markers."""
    blocks: list[str] = []
    current: list[str] = []
    line_no = 1
    for line in excerpts:
        if line == OMIT_MARKER:
            if current:
                blocks.append("\n".join(current))
                current = []
            blocks.append(OMIT_MARKER)
            continue
        current.append(f"{line_no:>5}| {line}")
        line_no += 1
    if current:
        blocks.append("\n".join(current))

    rendered = [block if block == OMIT_MARKER else f"```\n{block}\n```" for block in blocks]
    return "\n".join(rendered)


def build_implementation_prompt(
    task: str,
    bundle: ContextBundle,
    implementation_plan: ImplementationPlan,
    model: str,
    memory_context: list[MemorySearchResult] | None = None,
) -> tuple[str, str | None]:
    """Construct a provider prompt that asks only for a raw unified diff."""
    file_table_rows, _ = build_context_sections(bundle)
    file_details = build_budgeted_numbered_file_details(task, bundle)
    edit_plan = render_edit_plan(derive_edit_plan(task, bundle))
    result = _IMPLEMENTATION_TEMPLATE.format(
        system_instructions=_IMPLEMENTATION_SYSTEM_INSTRUCTIONS,
        task=task,
        model=model,
        workset_name=bundle.workset_name,
        query=bundle.query,
        root=bundle.root,
        generated_at=bundle.generated_at,
        file_table_rows=file_table_rows,
        file_details=file_details,
        edit_plan=edit_plan,
        implementation_plan=implementation_plan.content,
    )
    test_warning: str | None = None
    task_mentions_tests = any(
        keyword in task.lower() for keyword in ("test", "tests", "spec", "specs")
    )
    if task_mentions_tests:
        has_test_files = any(_is_test_file(file.path) for file in bundle.files)
        if has_test_files:
            result += _TEST_GUIDANCE
        else:
            result += _TEST_MISSING_NOTE
            test_warning = (
                "Task mentions tests, but no test files were present in the workset. "
                "Consider refreshing the workset with a test-focused query."
            )

    if memory_context:
        result = (
            result
            + "\n\n"
            + build_memory_section(
                memory_context,
                guidance=(
                    "Use these entries to preserve continuity while still returning only "
                    "a raw unified diff."
                ),
            )
        )
        result += "\n\nReturn only a raw unified diff. No Markdown fences. No explanations.\n"
    return result, test_warning


def build_repair_prompt(
    task: str,
    original_patch: str,
    structural_errors: list[str],
    apply_check_error: str,
    file_details: str,
    context_mismatches: list[str] | None = None,
    targeted_file_excerpts: str | None = None,
) -> str:
    """Build a prompt asking the model to repair an invalid patch."""
    error_lines = (
        "\n".join(f"- {error}" for error in structural_errors)
        if structural_errors
        else "(none)"
    )
    mismatch_section = ""
    if context_mismatches:
        mismatch_lines = "\n".join(f"- {m}" for m in context_mismatches)
        mismatch_section = f"""
## Exact Context Mismatches (your patch vs. the real file on disk)
Your previous patch's context or removed lines do NOT match the actual file content below.
This is almost certainly why it failed to apply. Copy lines verbatim from the
"Relevant File Context" section instead of reconstructing them from memory.
{mismatch_lines}
"""
    targeted_section = ""
    if targeted_file_excerpts:
        targeted_section = f"""
## AUTHORITATIVE FILE CONTENT AT MISMATCH LOCATIONS (read fresh from disk)
The excerpts below show the EXACT current content of the file at and around
each mismatched line (marked >>>). These lines were read directly from disk
right now and are ground truth. Your patch context lines MUST match them
character-for-character. Do NOT reconstruct these lines from memory or
from any prior version of the file — use only what is shown here.

{targeted_file_excerpts}
"""
    return f"""\
{_IMPLEMENTATION_SYSTEM_INSTRUCTIONS}

---

# Patch Repair Request

The patch you previously generated failed validation. You must return a corrected raw unified diff.

## Original Task
{task}

## Validation Errors (structural)
{error_lines}

## git apply --check Error
{apply_check_error or "(none)"}
{mismatch_section}{targeted_section}
## Original Invalid Patch
{original_patch}

## Relevant File Context
{file_details}

---

# Requirements

Return ONLY a corrected raw unified diff.
No Markdown fences.
No prose.
No explanations.
Hunk line counts in @@ markers must be exact. The file context above is
line-numbered with a "N| " gutter for exactly this purpose — read the
correct starting line and count off the gutter; never copy the gutter
itself into the diff.
Existing files listed in the original context must use standard unified diff hunks.
Never use /dev/null for existing files.
The corrected patch must pass: git apply --check
"""


_SRP_SYSTEM_INSTRUCTIONS = """\
You are a senior software engineer generating targeted file edits.

STRICT OUTPUT CONTRACT:
- Return only SEARCH/REPLACE blocks — no explanations, no Markdown fences, no prose.
- Each block must be preceded by the file path (relative to the repository root) on
  its own line immediately before <<<<<<< SEARCH.
- Use the exact format shown below — delimiter lines must be verbatim:

  path/to/File.java
  <<<<<<< SEARCH
  <exact lines to find, verbatim from the file>
  =======
  <replacement lines>
  >>>>>>> REPLACE

SEARCH CONTENT RULES:
- The SEARCH section must copy lines VERBATIM from the file — character for character,
  including all indentation, whitespace, and punctuation.
- Include 3-5 lines of surrounding context on each side of every change so the block
  is unique in the file.
- NEVER reconstruct SEARCH lines from memory; read them from the "Editable File
  Content" section provided below.
- If you need to change multiple non-adjacent regions of the same file, emit a
  separate block for each region.

REPLACE CONTENT RULES:
- The REPLACE section is the new content that replaces the SEARCH content exactly.
- Do not include files or symbols not in the workset unless genuinely necessary.
- Preserve existing architecture, style, and indentation.

WHAT NOT TO DO:
- Do not wrap blocks in Markdown code fences.
- Do not add explanatory text before, between, or after blocks.
- You may ONLY emit SEARCH/REPLACE blocks for files listed under Approved Editable Files.
- Any block for any other file will be rejected.
- Context-only files are not editable — they have no SEARCH-ready content below.
- Omitted files must not be modified.
"""

_SRP_TEMPLATE = """\
{system_instructions}

---

# Task
{task}

# Selected Model
{model}

# Workset
Name: {workset_name}
Query: {query}
Root: {root}
Generated: {generated_at}

# Workset Files (ALL EXISTING in repository)

| File | Category | Score | Lines | Symbols |
| --- | --- | ---: | ---: | --- |
{file_table_rows}

# Approved Editable Files

You may ONLY emit SEARCH/REPLACE blocks for these files:
{approved_editable_files}

Any block for any other file will be rejected.
Context-only files are not editable.
Omitted files must not be modified.

# Editable File Content

Full, SEARCH/REPLACE-ready content is provided below ONLY for the files listed
under Approved Editable Files above.

{editable_file_details}

# Context-Only Files

These files are provided for understanding only.
You may NOT emit SEARCH/REPLACE blocks for them.

{context_only_files}

{omitted_files_section}# Edit Targeting Plan

{edit_plan}

# Implementation Plan Or Notes

{implementation_plan}

---

# Final Response Requirements

Return ONLY SEARCH/REPLACE blocks using the exact format below — one block per
region changed, each preceded by the file path on its own line:

  path/to/File.java
  <<<<<<< SEARCH
  <verbatim lines to find>
  =======
  <replacement lines>
  >>>>>>> REPLACE

No Markdown fences. No prose. No explanations.
SEARCH content must match the file exactly, character for character.
You may ONLY emit blocks for files listed under Approved Editable Files.
Any block for any other file will be rejected.
"""

_SRP_TEST_GUIDANCE = """\

## Test File Requirement

The task explicitly requests tests. The Workset Files table above includes test files.
You MUST include SEARCH/REPLACE blocks for those test files.
Do not return blocks that only modify source files when the task requests tests.
"""

_SRP_TEST_MISSING_NOTE = """\

## Test File Warning

The task requests tests, but no test files are present in this workset.
The output will not include test changes unless test files are added to the workset.
"""

_SRP_REPAIR_SYSTEM = """\
You are a senior software engineer repairing failed SEARCH/REPLACE blocks.

The SEARCH/REPLACE blocks you previously generated could not be applied because the
SEARCH content did not match the file.  You must produce corrected blocks.

STRICT OUTPUT CONTRACT — same as the original request:
- Return only SEARCH/REPLACE blocks using the exact delimiter format.
- No Markdown fences. No prose. No explanations.
- SEARCH content must be verbatim from the "Authoritative File Content" section below.
- You may ONLY emit blocks for files listed under Approved Editable Files.
- Any block for any other file will be rejected.
"""

_SRP_REGENERATE_SYSTEM = """\
You are a senior software engineer regenerating SEARCH/REPLACE blocks after an
invalid attempt.

Your previous response emitted one or more SEARCH/REPLACE blocks for files that
are NOT in the approved editable target set. Those blocks were rejected outright
and were never applied to any file.

STRICT OUTPUT CONTRACT — same as the original request:
- Return only SEARCH/REPLACE blocks using the exact delimiter format.
- No Markdown fences. No prose. No explanations.
- You may ONLY emit blocks for files listed under Approved Editable Files below.
- Do not attempt to repair, resend, or resubmit edits for the rejected files —
  solve the task again using only the approved editable files.
- Any block for any other file will be rejected again.
"""


def build_search_replace_prompt(
    task: str,
    bundle: ContextBundle,
    implementation_plan: ImplementationPlan,
    model: str,
    memory_context: list[MemorySearchResult] | None = None,
    editable_targets: EditableTargetSet | None = None,
) -> tuple[str, str | None]:
    """Construct a provider prompt that asks for SEARCH/REPLACE blocks.

    Returns ``(prompt, test_warning)`` where ``test_warning`` is ``None`` when
    the workset contains test files (or the task does not mention tests) and a
    human-readable warning string when tests are missing from the workset.

    Implementation context is target-isolated (see
    ``forge.execution.context_budget.build_target_isolated_bundle``): full,
    SEARCH/REPLACE-ready content is only ever produced for approved editable
    targets. Workset files that are relevant but not approved for editing are
    summarized only; files outside the approved target's module are omitted
    from the prompt entirely.
    """
    editable_targets = editable_targets or select_editable_targets(task, bundle)
    approved_editable_files = _render_approved_editable_files(editable_targets)
    prompt_context = build_target_isolated_bundle(task, bundle, editable_targets)

    omitted_paths = {f.path for f in prompt_context.omitted_files}
    visible_files = [f for f in bundle.files if f.path not in omitted_paths]
    file_table_rows = _render_file_table(visible_files)

    editable_file_details = _render_editable_file_details(bundle, prompt_context.editable_files)
    context_only_files = _render_context_only_files(prompt_context.context_files)
    omitted_files_section = _render_omitted_files(prompt_context.omitted_files)

    editable_sub_bundle = ContextBundle(
        workset_name=bundle.workset_name,
        query=bundle.query,
        root=bundle.root,
        generated_at=bundle.generated_at,
        files=[f for f in bundle.files if f.path in prompt_context.approved_paths],
    )
    edit_plan = render_edit_plan(derive_edit_plan(task, editable_sub_bundle))
    result = _SRP_TEMPLATE.format(
        system_instructions=_SRP_SYSTEM_INSTRUCTIONS,
        task=task,
        model=model,
        workset_name=bundle.workset_name,
        query=bundle.query,
        root=bundle.root,
        generated_at=bundle.generated_at,
        file_table_rows=file_table_rows,
        approved_editable_files=approved_editable_files,
        editable_file_details=editable_file_details,
        context_only_files=context_only_files,
        omitted_files_section=omitted_files_section,
        edit_plan=edit_plan,
        implementation_plan=implementation_plan.content,
    )
    test_warning: str | None = None
    task_mentions_tests = any(
        keyword in task.lower() for keyword in ("test", "tests", "spec", "specs")
    )
    if task_mentions_tests:
        has_test_files = any(_is_test_file(file.path) for file in bundle.files)
        if has_test_files:
            result += _SRP_TEST_GUIDANCE
        else:
            result += _SRP_TEST_MISSING_NOTE
            test_warning = (
                "Task mentions tests, but no test files were present in the workset. "
                "Consider refreshing the workset with a test-focused query."
            )
    if memory_context:
        result = (
            result
            + "\n\n"
            + build_memory_section(
                memory_context,
                guidance=(
                    "Use these entries to preserve continuity while still returning only "
                    "SEARCH/REPLACE blocks."
                ),
            )
        )
        result += (
            "\n\nReturn only SEARCH/REPLACE blocks using the exact delimiter format. "
            "No Markdown fences. No explanations.\n"
        )
    return result, test_warning


def _render_approved_editable_files(editable_targets: EditableTargetSet) -> str:
    if not editable_targets.targets:
        return "- (none)"
    lines: list[str] = []
    for target in editable_targets.targets:
        required = " Required." if target.required else ""
        lines.append(f"- {target.path}\n  Reason: {target.reason}.{required}")
    return "\n".join(lines)


def _render_file_table(files: list[ContextBundleFile]) -> str:
    """Render the compact File/Category/Score/Lines/Symbols summary table.

    Unlike ``build_context_sections``, this takes an explicit file list so
    callers can exclude omitted (cross-module, non-editable) files from the
    table entirely rather than just from the detailed content sections.
    """
    rows: list[str] = []
    for f in files:
        symbols_preview = ", ".join(f.symbols[:5]) if f.symbols else "-"
        rows.append(f"| {f.path} | {f.category} | {f.score} | {f.line_count} | {symbols_preview} |")
    return "\n".join(rows) if rows else "| (no files) | - | - | - | - |"


def _render_editable_file_details(
    bundle: ContextBundle, editable_files: list[BudgetedFileContext]
) -> str:
    """Render full, SEARCH/REPLACE-ready content for approved editable files only.

    This is the only renderer in the SEARCH/REPLACE pipeline that emits
    verbatim, line-numbered source. It is intentionally driven by
    ``editable_files`` (the output of
    ``forge.execution.context_budget.build_target_isolated_bundle``), never by
    the full workset, so a file that is not an approved editable target can
    never appear here.
    """
    budgeted = {item.path: item for item in editable_files}
    parts: list[str] = []
    for f in bundle.files:
        decision = budgeted.get(f.path)
        if decision is None:
            continue
        section: list[str] = [
            f"### {f.path}",
            "**Editable:** yes — SEARCH/REPLACE blocks are permitted for this file.",
            f"Content mode: {decision.content_mode}",
            f"Reason: {decision.reason}",
        ]
        if f.error:
            section.append(f"**Error:** {f.error}")
            parts.append("\n".join(section))
            continue

        if f.summary:
            section.append("**Summary:** " + " | ".join(f.summary[:5]))
        if f.symbols:
            section.append("**Symbols:** " + ", ".join(f.symbols[:10]))
        if f.dependency_hints:
            section.append("**Dependencies:** " + "; ".join(f.dependency_hints[:8]))
        if decision.lines:
            section.append(
                "**File Content (verbatim from disk, SEARCH/REPLACE-ready, with a "
                "'N| ' line-number gutter for your reference only — the gutter is NOT "
                "part of the file and must NEVER appear in a SEARCH or REPLACE block; "
                "preserve indentation and whitespace after the gutter exactly):**"
            )
            section.append(_render_numbered_excerpt_blocks(decision.lines))
        elif decision.summary_only:
            section.append("**File Content:** omitted by implementation context budget.")
        parts.append("\n".join(section))
    return "\n\n".join(parts) if parts else "(no approved editable files with content)"


def _render_context_only_files(context_files: list[ContextBundleFile]) -> str:
    """Render safe, non-SEARCH-ready summaries for context-only files.

    Deliberately never includes verbatim multi-line source or line-numbered
    content — only category, a short "why included" hint, and symbol names —
    so a context-only file cannot be mistaken for an editable one.
    """
    if not context_files:
        return "(no context-only files)"
    lines = ["| File | Category | Why Included | Symbols |", "| --- | --- | --- | --- |"]
    for f in context_files:
        symbols_preview = ", ".join(f.symbols[:6]) if f.symbols else "-"
        why = (
            " | ".join(f.summary[:2])
            if f.summary
            else "related workset file, not an approved editable target"
        )
        lines.append(f"| {f.path} | {f.category} | {why} | {symbols_preview} |")
    return "\n".join(lines)


def _render_omitted_files(omitted_files: list[ContextBundleFile]) -> str:
    """Render an optional diagnostic list of cross-module files left out of the prompt.

    Returns an empty string when there is nothing to omit, so the caller can
    splice this directly into a template without leaving a dangling heading.
    """
    if not omitted_files:
        return ""
    lines = [
        "# Omitted Workset Files",
        "",
        "The following workset files were omitted from implementation context "
        "because they are outside the approved target's module or not editable. "
        "They must not be modified:",
        "",
    ]
    lines.extend(f"- {f.path}" for f in omitted_files)
    return "\n".join(lines) + "\n\n"


def build_target_isolated_file_details(
    task: str,
    bundle: ContextBundle,
    editable_targets: EditableTargetSet,
) -> str:
    """Render target-isolated file context for repair/regeneration prompts.

    Shared by ``build_search_replace_repair_prompt`` and
    ``build_search_replace_regenerate_prompt`` so repair follow-ups never
    resend full content for files outside the approved editable target set —
    only the same editable/context split used by the initial prompt.
    """
    prompt_context = build_target_isolated_bundle(task, bundle, editable_targets)
    editable_section = _render_editable_file_details(bundle, prompt_context.editable_files)
    parts = ["## Editable File Content (SEARCH/REPLACE-ready)", "", editable_section]
    if prompt_context.context_files:
        context_section = _render_context_only_files(prompt_context.context_files)
        parts += ["", "## Context-Only Files (not editable)", "", context_section]
    return "\n".join(parts)


def build_search_replace_repair_prompt(
    task: str,
    original_response: str,
    failures: list[str],
    file_details: str,
    failure_details: list[Any] | None = None,
    authoritative_excerpts: str | None = None,
    editable_targets: EditableTargetSet | None = None,
) -> str:
    """Build a prompt asking the model to repair failed SEARCH/REPLACE blocks.

    ``failures`` is a list of human-readable error strings from the applier
    (e.g. "SEARCH content not found", "ambiguous match").
    ``authoritative_excerpts`` is a formatted string of disk-fresh file excerpts
    at the failed locations, produced by ``_targeted_disk_excerpts``.
    ``editable_targets``, when provided, adds an "Approved Editable Files"
    section so repair attempts stay target-isolated instead of implicitly
    reopening the full workset.
    """
    failure_lines = (
        "\n".join(f"- {f}" for f in failures) if failures else "(none)"
    )
    approved_section = ""
    if editable_targets is not None:
        approved_section = f"""
## Approved Editable Files

You may ONLY emit SEARCH/REPLACE blocks for these files:
{_render_approved_editable_files(editable_targets)}

Any block for any other file will be rejected.
"""
    structured_section = ""
    if failure_details:
        detail_lines: list[str] = []
        for detail in failure_details:
            detail_lines.append(f"### {detail.file_path}")
            detail_lines.append(f"- error_type: {detail.error_type}")
            if detail.match_count is not None:
                detail_lines.append(f"- match_count: {detail.match_count}")
            if detail.message:
                detail_lines.append(f"- message: {detail.message}")
            if detail.search_preview:
                detail_lines.append("- search_preview:")
                detail_lines.append("```")
                detail_lines.append(detail.search_preview)
                detail_lines.append("```")
            if detail.nearest_match_excerpt:
                detail_lines.append("- nearest_match_excerpt:")
                detail_lines.append("```")
                detail_lines.append(detail.nearest_match_excerpt)
                detail_lines.append("```")
            detail_lines.append("")
        structured_section = "\n## Structured Failure Details\n" + "\n".join(detail_lines)
    auth_section = ""
    if authoritative_excerpts:
        auth_section = f"""
## Authoritative File Content At Failure Locations (read fresh from disk)

The excerpts below show the EXACT current file content around each failed SEARCH
block (>>> marks the approximate target region). Copy SEARCH lines verbatim from
these excerpts — do NOT reconstruct them from memory or from the original response.

{authoritative_excerpts}
"""
    return f"""\
{_SRP_REPAIR_SYSTEM}

---

# Patch Repair Request

The SEARCH/REPLACE blocks you previously generated could not be applied.

## Original Task
{task}
{approved_section}
## Application Failures
{failure_lines}
{structured_section}
{auth_section}
## Original (Failed) Response
{original_response}

## Relevant File Context
{file_details}

---

# Requirements

Return ONLY corrected SEARCH/REPLACE blocks using the exact delimiter format:

  path/to/File.java
  <<<<<<< SEARCH
  <verbatim lines from the Authoritative File Content or Relevant File Context above>
  =======
  <replacement lines>
  >>>>>>> REPLACE

No Markdown fences. No prose. No explanations.
Each SEARCH block must match the file exactly, character for character.
You may ONLY emit blocks for files listed under Approved Editable Files.
"""


def build_search_replace_regenerate_prompt(
    task: str,
    original_response: str,
    rejected_files: list[str],
    editable_targets: EditableTargetSet,
    file_details: str,
) -> str:
    """Build a prompt asking the model to regenerate blocks after a disallowed-file attempt.

    Used instead of ``build_search_replace_repair_prompt`` when the previous
    response emitted SEARCH/REPLACE blocks for files outside the approved
    editable target set. Unlike a normal repair, this does not try to salvage
    the rejected edits (no authoritative excerpts for them, no attempt to fix
    their SEARCH content) — it names the rejected files explicitly and asks
    the model to solve the task again using only approved editable files.
    ``file_details`` should come from ``build_target_isolated_file_details`` so
    the rejected files' content is never resent.
    """
    rejected_lines = (
        "\n".join(f"- {path}" for path in rejected_files) if rejected_files else "(none)"
    )
    return f"""\
{_SRP_REGENERATE_SYSTEM}

---

# Patch Regeneration Request

## Original Task
{task}

## Rejected Files (outside the approved editable target set — do not target these again)
{rejected_lines}

## Approved Editable Files

You may ONLY emit SEARCH/REPLACE blocks for these files:
{_render_approved_editable_files(editable_targets)}

Any block for any other file will be rejected again.

## Your Previous (Rejected) Response
{original_response}

## Relevant File Context
{file_details}

---

# Requirements

Return ONLY corrected SEARCH/REPLACE blocks targeting exclusively the files
listed under Approved Editable Files:

  path/to/File.java
  <<<<<<< SEARCH
  <verbatim lines from the Relevant File Context above>
  =======
  <replacement lines>
  >>>>>>> REPLACE

No Markdown fences. No prose. No explanations.
Do not emit any block for a rejected or non-approved file.
"""


def _is_test_file(path: str) -> bool:
    lowered = path.lower()
    return (
        lowered.startswith("tests/")
        or "/tests/" in lowered
        or lowered.startswith("test_")
        or "/test_" in lowered
        or lowered.endswith(("_test.py", "_spec.py", ".spec.py", ".test.py"))
        or "test" in lowered
    )
