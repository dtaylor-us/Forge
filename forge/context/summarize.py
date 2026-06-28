"""Deterministic file summarization — no AI models."""

from __future__ import annotations

import json
import re


def summarize_file(content: str, suffix: str, path_str: str) -> list[str]:
    """Return a list of summary lines for the file."""
    ext = suffix.lower().lstrip(".")
    if ext == "py":
        return _summarize_python(content, path_str)
    if ext in ("java", "kt"):
        return _summarize_java(content, path_str)
    if ext in ("ts", "tsx", "js", "jsx"):
        return _summarize_ts(content, path_str)
    if ext == "md":
        return _summarize_markdown(content)
    if ext in ("yaml", "yml"):
        return _summarize_yaml(content, path_str)
    if ext == "toml":
        return _summarize_toml(content)
    if ext == "json":
        return _summarize_json(content, path_str)
    return _summarize_generic(content, path_str)


def _summarize_python(content: str, path_str: str) -> list[str]:  # noqa: ARG001
    lines = content.splitlines()
    summary = ["Python source file."]
    # module docstring
    stripped = content.lstrip()
    if stripped.startswith('"""') or stripped.startswith("'''"):
        q = stripped[:3]
        end = stripped.find(q, 3)
        if end != -1:
            doc = stripped[3:end].strip().splitlines()[0]
            if doc:
                summary.append(doc)
    cls_names = [m.group(1) for ln in lines if (m := re.match(r"^\s*class\s+(\w+)", ln))]
    if cls_names:
        plural = "es" if len(cls_names) > 1 else ""
        summary.append(f"Defines class{plural}: {', '.join(cls_names[:5])}.")
    func_names = [
        m.group(1)
        for ln in lines
        if (m := re.match(r"^\s*(?:async\s+)?def\s+(\w+)", ln)) and not m.group(1).startswith("_")
    ]
    if func_names:
        summary.append(f"Public functions: {', '.join(func_names[:8])}.")
    return summary


def _summarize_java(content: str, path_str: str) -> list[str]:  # noqa: ARG001
    lines = content.splitlines()
    summary = ["Java source file."]
    for line in lines:
        m = re.match(r"^\s*package\s+([\w.]+)", line)
        if m:
            summary.append(f"Package: {m.group(1)}.")
            break
    types = [
        m.group(1)
        for line in lines
        if (m := re.match(r"^\s*(?:public\s+)?(?:class|interface|enum|record)\s+(\w+)", line))
    ]
    if types:
        summary.append(f"Defines: {', '.join(types[:5])}.")
    _ann_pat = re.compile(
        r"^\s*(@(?:RestController|Service|Repository|Component" r"|Configuration|Controller|Bean))"
    )
    annotations = {m.group(1) for line in lines if (m := _ann_pat.match(line))}
    if annotations:
        summary.append(f"Annotations: {', '.join(sorted(annotations))}.")
    return summary


def _summarize_ts(content: str, path_str: str) -> list[str]:  # noqa: ARG001
    lines = content.splitlines()
    summary = ["TypeScript/JavaScript source file."]
    imports = [ln.strip() for ln in lines if re.match(r"^\s*import\s+", ln)]
    if imports:
        summary.append(f"{len(imports)} import(s).")
    exports = [ln.strip() for ln in lines if re.match(r"^\s*export\s+", ln)]
    if exports:
        summary.append(f"{len(exports)} export(s).")
    if any("React" in ln or "jsx" in ln.lower() or "tsx" in ln.lower() for ln in imports[:10]):
        summary.append("Likely React module.")
    return summary


def _summarize_markdown(content: str) -> list[str]:
    lines = content.splitlines()
    summary: list[str] = []
    title = next((ln.lstrip("#").strip() for ln in lines if ln.startswith("#")), None)
    if title:
        summary.append(f"Title: {title}.")
    headings = [ln.lstrip("#").strip() for ln in lines if re.match(r"^#{1,3}\s", ln)]
    if headings:
        summary.append(f"Sections: {', '.join(headings[:6])}.")
    non_empty = [ln for ln in lines if ln.strip() and not ln.startswith("#")]
    if non_empty:
        summary.append(f"First paragraph: {non_empty[0][:120]}")
    return summary or ["Markdown file."]


def _summarize_yaml(content: str, path_str: str) -> list[str]:  # noqa: ARG001
    lines = content.splitlines()
    top_keys = [
        m.group(1)
        for ln in lines
        if not ln.startswith(" ") and not ln.startswith("#")
        if (m := re.match(r"^(\w[\w.-]*)\s*:", ln))
    ]
    if top_keys:
        return [
            "YAML configuration file.",
            f"Top-level keys: {', '.join(top_keys[:10])}.",
        ]
    return ["YAML file."]


def _summarize_toml(content: str) -> list[str]:
    sections = re.findall(r"^\[([^\]]+)\]", content, re.MULTILINE)
    keys = re.findall(r"^(\w[\w.-]*)\s*=", content, re.MULTILINE)
    result = ["TOML configuration file."]
    if sections:
        result.append(f"Sections: {', '.join(sections[:8])}.")
    elif keys:
        result.append(f"Keys: {', '.join(keys[:8])}.")
    return result


def _summarize_json(content: str, path_str: str) -> list[str]:  # noqa: ARG001
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return ["JSON file (unparseable)."]
    if isinstance(data, dict):
        return ["JSON object.", f"Top-level keys: {', '.join(list(data.keys())[:10])}."]
    if isinstance(data, list):
        return [f"JSON array with {len(data)} element(s)."]
    return ["JSON file."]


def _summarize_generic(content: str, path_str: str) -> list[str]:  # noqa: ARG001
    lines = content.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]
    summary = [f"Text file. {len(lines)} lines, {len(content)} chars."]
    if non_empty:
        summary.append(f"First line: {non_empty[0][:100]}")
    return summary
