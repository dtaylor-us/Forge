"""Render context bundles as Markdown or JSON."""

from __future__ import annotations

import json
from pathlib import Path

from forge.context.bundle import ContextBundle


def render_markdown(bundle: ContextBundle) -> str:
    """Render a context bundle as a Markdown document."""
    lines: list[str] = []

    lines.append(f"# Forge Context Bundle: {bundle.workset_name}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- Workset: {bundle.workset_name}")
    lines.append(f"- Query: {bundle.query}")
    lines.append(f"- Root: {bundle.root}")
    lines.append(f"- Generated: {bundle.generated_at}")
    lines.append(f"- Files: {len(bundle.files)}")
    lines.append(f"- Character estimate: {bundle.total_chars:,}")
    lines.append(f"- Token estimate: {bundle.total_tokens:,}")
    lines.append("")

    lines.append("## Workset Files")
    lines.append("")
    lines.append("| Path | Category | Score | Lines | Chars |")
    lines.append("| --- | --- | ---: | ---: | ---: |")
    for f in bundle.files:
        lines.append(
            f"| {f.path} | {f.category} | {f.score} | {f.line_count:,} | {f.char_count:,} |"
        )
    lines.append("")

    lines.append("## File Context")
    lines.append("")
    for f in bundle.files:
        lines.append(f"### {f.path}")
        lines.append("")

        if f.reasons:
            lines.append("**Reason selected**")
            for r in f.reasons:
                lines.append(f"- {r}")
            lines.append("")

        if f.error:
            lines.append(f"**Error:** {f.error}")
            lines.append("")
            continue

        if f.summary:
            lines.append("**File summary**")
            for s in f.summary:
                lines.append(f"- {s}")
            lines.append("")

        if f.symbols:
            lines.append("**Detected symbols**")
            for s in f.symbols:
                lines.append(f"- {s}")
            lines.append("")

        if f.dependency_hints:
            lines.append("**Dependency hints**")
            for d in f.dependency_hints:
                lines.append(f"- {d}")
            lines.append("")

        if f.excerpts:
            ext = Path(f.path).suffix.lstrip(".") or "text"
            lines.append("**Relevant excerpt**")
            lines.append(f"```{ext}")
            lines.extend(f.excerpts)
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def render_json(bundle: ContextBundle) -> str:
    """Render a context bundle as JSON."""
    data = {
        "schema_version": 1,
        "workset": bundle.workset_name,
        "query": bundle.query,
        "root": bundle.root,
        "generated_at": bundle.generated_at,
        "total_chars": bundle.total_chars,
        "total_tokens": bundle.total_tokens,
        "files": [
            {
                "path": f.path,
                "category": f.category,
                "score": f.score,
                "line_count": f.line_count,
                "char_count": f.char_count,
                "token_estimate": f.token_estimate,
                "summary": f.summary,
                "symbols": f.symbols,
                "dependency_hints": f.dependency_hints,
                "excerpts": f.excerpts,
                "reasons": f.reasons,
                "error": f.error,
            }
            for f in bundle.files
        ],
    }
    return json.dumps(data, indent=2)
