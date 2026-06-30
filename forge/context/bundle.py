"""Context bundle orchestration — loads workset, reads files, produces typed bundle."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge.context.excerpt import OMIT_MARKER, extract_excerpts
from forge.context.summarize import summarize_file
from forge.context.symbols import extract_symbols
from forge.worksets.store import load

SCHEMA_VERSION = 1
_BINARY_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "bmp",
    "ico",
    "svg",
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "zip",
    "tar",
    "gz",
    "bz2",
    "7z",
    "rar",
    "exe",
    "dll",
    "so",
    "dylib",
    "a",
    "o",
    "pyc",
    "pyo",
    "class",
    "mp3",
    "mp4",
    "avi",
    "mov",
    "mkv",
    "ttf",
    "otf",
    "woff",
    "woff2",
}


def _estimate_tokens(char_count: int) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, char_count // 4)


def _extract_dependency_hints(content: str, suffix: str) -> list[str]:
    ext = suffix.lower().lstrip(".")
    hints: list[str] = []
    if ext == "py":
        for line in content.splitlines():
            m = re.match(r"^\s*(?:from|import)\s+([\w.]+)", line)
            if m:
                hints.append(f"imports {m.group(1)}")
    elif ext in ("java", "kt"):
        for line in content.splitlines():
            m = re.match(r"^\s*import\s+([\w.]+)", line)
            if m:
                hints.append(f"imports {m.group(1)}")
    elif ext in ("ts", "tsx", "js", "jsx"):
        for line in content.splitlines():
            m = re.match(r"""^\s*import\s+.*from\s+['"]([^'"]+)['"]""", line)
            if m:
                hints.append(f"imports {m.group(1)}")
    return hints[:20]


@dataclass
class ContextBundleFile:
    path: str
    category: str
    score: int
    line_count: int
    char_count: int
    token_estimate: int
    summary: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    dependency_hints: list[str] = field(default_factory=list)
    excerpts: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ContextBundle:
    workset_name: str
    query: str
    root: str
    generated_at: str
    files: list[ContextBundleFile] = field(default_factory=list)
    total_chars: int = 0
    total_tokens: int = 0


def _build_file_entry(
    root: Path,
    file_entry: dict[str, Any],
    query_tokens: list[str],
    *,
    max_lines: int,
    include_full: bool,
) -> ContextBundleFile:
    rel_path = file_entry["path"]
    category = file_entry.get("category", "source")
    score = file_entry.get("score", 0)
    reasons = [
        f"{r.get('signal', '')}:{r.get('detail', '')} (+{r.get('points', 0)})"
        for r in file_entry.get("reasons", [])
    ]

    abs_path = root / rel_path
    suffix = Path(rel_path).suffix

    if suffix.lstrip(".").lower() in _BINARY_EXTENSIONS:
        return ContextBundleFile(
            path=rel_path,
            category=category,
            score=score,
            line_count=0,
            char_count=0,
            token_estimate=0,
            reasons=reasons,
            error="Binary or unsupported file type; contents not included.",
        )

    if not abs_path.exists():
        return ContextBundleFile(
            path=rel_path,
            category=category,
            score=score,
            line_count=0,
            char_count=0,
            token_estimate=0,
            reasons=reasons,
            error="File not found.",
        )

    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return ContextBundleFile(
            path=rel_path,
            category=category,
            score=score,
            line_count=0,
            char_count=0,
            token_estimate=0,
            reasons=reasons,
            error=f"Could not read file: {exc}",
        )

    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    char_count = len(content)
    token_estimate = _estimate_tokens(char_count)

    summary = summarize_file(content, suffix, rel_path)
    symbols = extract_symbols(content, suffix)
    dep_hints = _extract_dependency_hints(content, suffix)
    excerpts = extract_excerpts(
        content,
        query_tokens,
        max_lines=max_lines,
        include_full=include_full,
    )

    return ContextBundleFile(
        path=rel_path,
        category=category,
        score=score,
        line_count=line_count,
        char_count=char_count,
        token_estimate=token_estimate,
        summary=summary,
        symbols=symbols,
        dependency_hints=dep_hints,
        excerpts=excerpts,
        reasons=reasons,
    )


def generate_bundle(
    root: Path,
    workset_name: str,
    *,
    max_lines_per_file: int = 60,
    include_full: bool = False,
) -> ContextBundle:
    """Load a persisted workset and produce a ContextBundle."""
    data = load(root, workset_name)
    query: str = data.get("query", "")
    query_tokens: list[str] = [t for t in query.lower().split() if len(t) > 2]
    generated_at = datetime.now(tz=UTC).isoformat(timespec="seconds")

    bundle = ContextBundle(
        workset_name=workset_name,
        query=query,
        root=str(root),
        generated_at=generated_at,
    )

    for file_entry in data.get("files", []):
        bf = _build_file_entry(
            root,
            file_entry,
            query_tokens,
            max_lines=max_lines_per_file,
            include_full=include_full,
        )
        bundle.files.append(bf)
        bundle.total_chars += bf.char_count
        bundle.total_tokens += bf.token_estimate

    if include_full:
        _enforce_bundle_budget(bundle)

    return bundle


# Total excerpt budget for a bundle in include_full mode. Keeps the prompt
# within reach of small/local models even when the workset has many or large
# files; lowest-scored files are demoted to excerpts first.
_MAX_BUNDLE_EXCERPT_CHARS = 150_000


def _enforce_bundle_budget(bundle: ContextBundle) -> None:
    rendered_size = sum(sum(len(line) for line in f.excerpts) for f in bundle.files)
    if rendered_size <= _MAX_BUNDLE_EXCERPT_CHARS:
        return

    for f in sorted(bundle.files, key=lambda f: f.score):
        if rendered_size <= _MAX_BUNDLE_EXCERPT_CHARS:
            break
        before = sum(len(line) for line in f.excerpts)
        if len(f.excerpts) > 60:
            f.excerpts = f.excerpts[:60] + [OMIT_MARKER]
        rendered_size -= before - sum(len(line) for line in f.excerpts)


def save_bundle_markdown(bundle: ContextBundle, output_path: Path, markdown: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
