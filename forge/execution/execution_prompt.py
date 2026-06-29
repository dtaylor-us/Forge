"""Build Engineering Execution prompts from prepared orchestration inputs."""

from __future__ import annotations

from forge.context.bundle import ContextBundle
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
Hunk counts in @@ markers must be exact.
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


def build_implementation_prompt(
    task: str,
    bundle: ContextBundle,
    implementation_plan: ImplementationPlan,
    model: str,
    memory_context: list[MemorySearchResult] | None = None,
) -> tuple[str, str | None]:
    """Construct a provider prompt that asks only for a raw unified diff."""
    file_table_rows, file_details = build_context_sections(bundle)
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
) -> str:
    """Build a prompt asking the model to repair an invalid patch."""
    error_lines = (
        "\n".join(f"- {error}" for error in structural_errors)
        if structural_errors
        else "(none)"
    )
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
Hunk line counts in @@ markers must be exact.
Existing files listed in the original context must use standard unified diff hunks.
Never use /dev/null for existing files.
The corrected patch must pass: git apply --check
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
