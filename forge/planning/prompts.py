"""Build planning prompts from workset context bundles."""

from __future__ import annotations

from forge.context.bundle import ContextBundle
from forge.context.excerpt import OMIT_MARKER
from forge.memory.search import MemorySearchResult

_PLANNING_SYSTEM_INSTRUCTIONS = """\
You are a senior software architect producing an implementation plan.

STRICT RULES:
- Do NOT generate code patches or diffs.
- Do NOT claim any files have been modified.
- Do NOT modify any files.
- Reason only from the context provided below.
- Clearly mark anything you are uncertain about.
- Distinguish between files "likely to change" vs files that "need inspection first".
- Always recommend tests.
- Preserve human review — your plan is advisory, not executable.

Output format: Markdown with the exact section headings specified in the prompt.
"""

_PLAN_TEMPLATE = """\
{system_instructions}

---

# Planning Request

## Task
{task}

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

---

# Output Required

Produce an implementation plan in exactly this Markdown structure:

```markdown
# Forge Implementation Plan

## Task

## Workset Used

## Objective

## Current Understanding

## Files Likely to Change

| File | Reason | Change Type |
| --- | --- | --- |

## Files to Inspect Before Editing

## Proposed Implementation Steps

## Testing Strategy

## Risks and Edge Cases

## Questions or Blockers

## Suggested Commit Scope

## Follow-Up Work
```

At the end of the plan, include this footer verbatim:

---
*This is a plan only. No files were modified.*
*Workset used: {workset_name}. Model: {{model_placeholder}}.*
"""


def build_planning_prompt(
    task: str,
    bundle: ContextBundle,
    model: str,
    memory_context: list[MemorySearchResult] | None = None,
) -> str:
    """Construct the full planning prompt from a task and context bundle."""
    file_table_rows, file_details = build_context_sections(bundle)

    raw = _PLAN_TEMPLATE.format(
        system_instructions=_PLANNING_SYSTEM_INSTRUCTIONS,
        task=task,
        workset_name=bundle.workset_name,
        query=bundle.query,
        root=bundle.root,
        generated_at=bundle.generated_at,
        file_table_rows=file_table_rows,
        file_details=file_details,
    )
    result = raw.replace("{model_placeholder}", model)
    if memory_context:
        result = result + "\n\n" + build_memory_section(memory_context)
    return result


def build_context_sections(bundle: ContextBundle) -> tuple[str, str]:
    """Render reusable context sections for planning-adjacent prompts."""
    return _build_file_table(bundle), _build_file_details(bundle)


def build_memory_section(
    memory_results: list[MemorySearchResult],
    *,
    guidance: str = "Use them to inform your plan.",
) -> str:
    """Render reusable engineering memory context for planning-adjacent prompts."""
    lines = ["## Engineering Memory Context", ""]
    lines.append(
        "The following prior engineering artifacts are relevant to this task. " f"{guidance}"
    )
    lines.append("")
    for r in memory_results:
        item = r.item
        lines.append(f"### [{item.type.value.upper()}] {item.title} (id: {item.id})")
        lines.append(f"- **Created:** {item.created_at}")
        if item.workset:
            lines.append(f"- **Workset:** {item.workset}")
        if item.tags:
            lines.append(f"- **Tags:** {', '.join(item.tags)}")
        if item.summary:
            lines.append(f"- **Summary:** {item.summary}")
        if item.related_files:
            lines.append(f"- **Related files:** {', '.join(item.related_files[:5])}")
        if r.reasons:
            match_desc = "; ".join(f"{r2.signal}({r2.detail})" for r2 in r.reasons[:3])
            lines.append(f"- **Matched because:** {match_desc}")
        lines.append("")
    return "\n".join(lines)


def _build_file_table(bundle: ContextBundle) -> str:
    rows: list[str] = []
    for f in bundle.files:
        symbols_preview = ", ".join(f.symbols[:5]) if f.symbols else "-"
        rows.append(f"| {f.path} | {f.category} | {f.score} | {f.line_count} | {symbols_preview} |")
    return "\n".join(rows) if rows else "| (no files) | - | - | - | - |"


def _build_file_details(bundle: ContextBundle) -> str:
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
                "**File Content (verbatim — copied exactly from the real file on disk; "
                "preserve indentation and whitespace exactly, do not paraphrase or "
                "reconstruct from memory):**"
            )
            section.append(_render_excerpt_blocks(f.excerpts))
        parts.append("\n".join(section))
    return "\n\n".join(parts)


def _render_excerpt_blocks(excerpts: list[str]) -> str:
    """Render excerpt lines as contiguous, indentation-preserving code blocks.

    `excerpts` is a flat per-line sequence (one list entry per source line),
    with `OMIT_MARKER` entries standing in for skipped regions. Earlier code
    fenced only the first few entries individually, which (a) discarded
    nearly all real file content beyond the first couple of lines and
    (b) stripped each line's leading whitespace, destroying indentation.
    This renders every contiguous run of real lines as a single fenced
    block, splitting only at omitted regions, so the model sees the actual
    file content rather than a near-empty fragment.
    """
    blocks: list[str] = []
    current: list[str] = []
    for line in excerpts:
        if line == OMIT_MARKER:
            if current:
                blocks.append("\n".join(current))
                current = []
            blocks.append(OMIT_MARKER)
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))

    rendered = [block if block == OMIT_MARKER else f"```\n{block}\n```" for block in blocks]
    return "\n".join(rendered)
