"""Tests for Phase 2F: workset context bundle generation."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from forge.cli.app import app
from forge.context.bundle import generate_bundle
from forge.context.excerpt import extract_excerpts
from forge.context.render import render_json, render_markdown
from forge.context.summarize import summarize_file
from forge.context.symbols import extract_symbols
from forge.worksets.store import save

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workset(root: Path, name: str = "my-ws", query: str = "model config") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "name": name,
        "query": query,
        "root": str(root),
        "created_at": "2026-06-28T00:00:00+00:00",
        "updated_at": "2026-06-28T00:00:00+00:00",
        "include_tests": False,
        "max_results": 10,
        "files": [],
    }
    return save(root, data)


def _add_file_entry(root: Path, ws_name: str, rel_path: str, content: str) -> None:
    """Write a source file and add it to the workset JSON."""
    abs_path = root / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")

    ws_path = root / ".forge" / "worksets" / f"{ws_name}.json"
    data = json.loads(ws_path.read_text())
    data["files"].append(
        {
            "path": rel_path,
            "score": 10,
            "category": "source",
            "reasons": [{"signal": "filename", "detail": "matched query", "points": 10}],
            "manual": False,
        }
    )
    ws_path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


def test_python_symbol_extraction():
    code = """\
class Foo:
    pass

def bar(x, y):
    return x + y

async def baz():
    pass
"""
    symbols = extract_symbols(code, ".py")
    assert any("class Foo" in s for s in symbols)
    assert any("def bar" in s for s in symbols)
    assert any("def baz" in s for s in symbols)


def test_java_symbol_extraction():
    code = """\
@RestController
public class UserController {
    public void getUser(String id) {}
}
"""
    symbols = extract_symbols(code, ".java")
    assert any("UserController" in s for s in symbols)


def test_ts_symbol_extraction():
    code = """\
export class AuthService {}
export const login = () => {};
"""
    symbols = extract_symbols(code, ".ts")
    assert any("AuthService" in s for s in symbols)


def test_unknown_extension_returns_empty():
    assert extract_symbols("hello world", ".xyz") == []


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------


def test_summarize_python():
    code = "class Foo:\n    pass\n\ndef bar():\n    pass\n"
    summary = summarize_file(code, ".py", "foo.py")
    joined = " ".join(summary)
    assert "Python" in joined
    assert "Foo" in joined


def test_summarize_markdown():
    md = "# My Title\n\n## Section One\n\nFirst paragraph text.\n"
    summary = summarize_file(md, ".md", "README.md")
    joined = " ".join(summary)
    assert "My Title" in joined


def test_summarize_yaml():
    yaml_content = "database:\n  host: localhost\nserver:\n  port: 8080\n"
    summary = summarize_file(yaml_content, ".yaml", "config.yaml")
    joined = " ".join(summary)
    assert "database" in joined or "server" in joined


def test_summarize_toml():
    toml_content = "[tool.poetry]\nname = 'forge'\n[tool.ruff]\nline-length = 100\n"
    summary = summarize_file(toml_content, ".toml", "pyproject.toml")
    joined = " ".join(summary)
    assert "TOML" in joined


def test_summarize_json():
    j = '{"name": "forge", "version": "0.1.0"}'
    summary = summarize_file(j, ".json", "package.json")
    joined = " ".join(summary)
    assert "name" in joined or "version" in joined


def test_summarize_java():
    code = "package com.example;\npublic class Service {}\n"
    summary = summarize_file(code, ".java", "Service.java")
    joined = " ".join(summary)
    assert "Java" in joined


# ---------------------------------------------------------------------------
# Excerpts
# ---------------------------------------------------------------------------


def test_excerpt_max_lines():
    content = "\n".join(f"line {i}" for i in range(200))
    excerpts = extract_excerpts(content, [], max_lines=30)
    assert len(excerpts) <= 32  # allow for omit markers


def test_excerpt_query_match():
    lines = ["import os", "x = 1", "def configure_model():", "    pass"]
    content = "\n".join(lines)
    excerpts = extract_excerpts(content, ["configure", "model"], max_lines=120)
    assert any("configure_model" in e for e in excerpts)


def test_excerpt_include_full():
    content = "\n".join(f"line {i}" for i in range(300))
    excerpts = extract_excerpts(content, [], max_lines=10, include_full=True)
    assert len(excerpts) == 300


def test_excerpt_omit_marker():
    content = "\n".join(f"line {i}" for i in range(100))
    excerpts = extract_excerpts(content, ["line 50"], max_lines=120)
    text = "\n".join(excerpts)
    assert "omitted" in text


# ---------------------------------------------------------------------------
# Bundle generation
# ---------------------------------------------------------------------------


def test_generate_bundle_basic(tmp_path: Path):
    _make_workset(tmp_path, "ws", "model config")
    _add_file_entry(tmp_path, "ws", "src/model.py", "class Model:\n    pass\n")
    bundle = generate_bundle(tmp_path, "ws")
    assert bundle.workset_name == "ws"
    assert bundle.query == "model config"
    assert len(bundle.files) == 1
    assert bundle.files[0].path == "src/model.py"
    assert bundle.total_chars > 0
    assert bundle.total_tokens > 0


def test_generate_bundle_missing_file(tmp_path: Path):
    _make_workset(tmp_path, "ws")
    ws_path = tmp_path / ".forge" / "worksets" / "ws.json"
    data = json.loads(ws_path.read_text())
    data["files"].append(
        {
            "path": "does_not_exist.py",
            "score": 0,
            "category": "source",
            "reasons": [],
            "manual": False,
        }
    )
    ws_path.write_text(json.dumps(data, indent=2))
    bundle = generate_bundle(tmp_path, "ws")
    assert len(bundle.files) == 1
    assert bundle.files[0].error == "File not found."


def test_generate_bundle_binary_file(tmp_path: Path):
    _make_workset(tmp_path, "ws")
    binary_path = tmp_path / "image.png"
    binary_path.write_bytes(b"\x89PNG\r\n")
    ws_path = tmp_path / ".forge" / "worksets" / "ws.json"
    data = json.loads(ws_path.read_text())
    data["files"].append(
        {
            "path": "image.png",
            "score": 0,
            "category": "source",
            "reasons": [],
            "manual": False,
        }
    )
    ws_path.write_text(json.dumps(data, indent=2))
    bundle = generate_bundle(tmp_path, "ws")
    assert bundle.files[0].error is not None
    assert "Binary" in bundle.files[0].error


def test_token_estimate(tmp_path: Path):
    _make_workset(tmp_path, "ws")
    content = "x" * 400
    _add_file_entry(tmp_path, "ws", "a.py", content)
    bundle = generate_bundle(tmp_path, "ws")
    assert bundle.files[0].token_estimate == 100  # 400 // 4


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def test_render_markdown_shape(tmp_path: Path):
    _make_workset(tmp_path, "ws", "model config")
    _add_file_entry(tmp_path, "ws", "src/model.py", "class Model:\n    pass\n")
    bundle = generate_bundle(tmp_path, "ws")
    md = render_markdown(bundle)
    assert "# Forge Context Bundle: ws" in md
    assert "## Metadata" in md
    assert "## Workset Files" in md
    assert "## File Context" in md
    assert "src/model.py" in md


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


def test_render_json_shape(tmp_path: Path):
    _make_workset(tmp_path, "ws", "model config")
    _add_file_entry(tmp_path, "ws", "src/model.py", "class Model:\n    pass\n")
    bundle = generate_bundle(tmp_path, "ws")
    j = render_json(bundle)
    data = json.loads(j)
    assert data["schema_version"] == 1
    assert data["workset"] == "ws"
    assert len(data["files"]) == 1
    assert "path" in data["files"][0]
    assert "token_estimate" in data["files"][0]


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_context_markdown(tmp_path: Path):
    _make_workset(tmp_path, "myws", "model config")
    _add_file_entry(tmp_path, "myws", "src/model.py", "class Model:\n    pass\n")
    result = runner.invoke(app, ["workset", "context", "myws", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Context bundle saved" in result.output


def test_cli_context_json(tmp_path: Path):
    _make_workset(tmp_path, "myws", "model config")
    _add_file_entry(tmp_path, "myws", "src/model.py", "class Model:\n    pass\n")
    result = runner.invoke(app, ["workset", "context", "myws", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["workset"] == "myws"


def test_cli_context_max_lines(tmp_path: Path):
    _make_workset(tmp_path, "myws", "lines")
    content = "\n".join(f"line {i}" for i in range(200))
    _add_file_entry(tmp_path, "myws", "big.py", content)
    result = runner.invoke(
        app, ["workset", "context", "myws", "--root", str(tmp_path), "--max-lines-per-file", "20"]
    )
    assert result.exit_code == 0, result.output


def test_cli_context_include_full(tmp_path: Path):
    _make_workset(tmp_path, "myws")
    _add_file_entry(tmp_path, "myws", "src/x.py", "# all lines\n" * 50)
    result = runner.invoke(
        app, ["workset", "context", "myws", "--root", str(tmp_path), "--include-full"]
    )
    assert result.exit_code == 0, result.output


def test_cli_context_output_path(tmp_path: Path):
    _make_workset(tmp_path, "myws")
    _add_file_entry(tmp_path, "myws", "a.py", "x = 1\n")
    out = tmp_path / "out" / "bundle.md"
    result = runner.invoke(
        app, ["workset", "context", "myws", "--root", str(tmp_path), "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "# Forge Context Bundle" in out.read_text()


def test_cli_context_missing_workset(tmp_path: Path):
    result = runner.invoke(app, ["workset", "context", "no-such-ws", "--root", str(tmp_path)])
    assert result.exit_code != 0
