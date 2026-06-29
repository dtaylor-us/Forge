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
- Include valid hunk markers.
- Use paths relative to the repository root.
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

# Workset Files Summary

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
) -> str:
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
    return result
