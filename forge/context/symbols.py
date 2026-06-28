"""Deterministic symbol extraction from source files."""

from __future__ import annotations

import re


def extract_symbols(content: str, suffix: str) -> list[str]:
    """Return detected symbols for a file given its content and extension suffix."""
    ext = suffix.lower().lstrip(".")
    if ext == "py":
        return _python_symbols(content)
    if ext in ("java", "kt", "scala"):
        return _java_symbols(content)
    if ext in ("ts", "tsx", "js", "jsx"):
        return _ts_symbols(content)
    return []


def _python_symbols(content: str) -> list[str]:
    symbols: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        m = re.match(r"^class\s+(\w+)", stripped)
        if m:
            symbols.append(f"class {m.group(1)}")
            continue
        m = re.match(r"^(async\s+)?def\s+(\w+)\s*\(([^)]*)\)", stripped)
        if m:
            params = m.group(3).strip()
            symbols.append(f"def {m.group(2)}({params[:40]}{'...' if len(params) > 40 else ''})")
    return symbols


def _java_symbols(content: str) -> list[str]:
    symbols: list[str] = []
    annotations: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        m = re.match(r"^(@\w+)", stripped)
        if m:
            annotations.append(m.group(1))
            continue
        m = re.match(
            r"^(?:public|private|protected|abstract|final|static|\s)*"
            r"(?:class|interface|enum|record)\s+(\w+)",
            stripped,
        )
        if m:
            ann_str = " ".join(annotations)
            label = f"{ann_str + ' ' if ann_str else ''}class {m.group(1)}"
            symbols.append(label.strip())
            annotations = []
            continue
        m = re.match(
            r"^(?:public|private|protected|static|final|abstract|synchronized|\s)*"
            r"(?:\w+[\[\]<>?,\s]*)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+)?\s*\{?",
            stripped,
        )
        if m and m.group(1) not in ("if", "for", "while", "switch", "catch", "try"):
            symbols.append(f"method {m.group(1)}(...)")
        annotations = []
    return symbols


def _ts_symbols(content: str) -> list[str]:
    symbols: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        m = re.match(r"^export\s+(default\s+)?class\s+(\w+)", stripped)
        if m:
            symbols.append(f"export class {m.group(2)}")
            continue
        m = re.match(r"^class\s+(\w+)", stripped)
        if m:
            symbols.append(f"class {m.group(1)}")
            continue
        m = re.match(r"^export\s+(const|function|async function)\s+(\w+)", stripped)
        if m:
            symbols.append(f"export {m.group(1)} {m.group(2)}")
            continue
        m = re.match(r"^(?:const|function|async function)\s+(\w+)", stripped)
        if m:
            symbols.append(f"{m.group(0).split('(')[0].strip()}")
    return symbols
