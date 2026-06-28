"""FastAPI web dependencies and template helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates


def templates(request: Request) -> Jinja2Templates:
    """Return the configured Jinja template renderer."""
    return request.app.state.templates


def repo_root(request: Request) -> Path:
    """Return the resolved repository root for this local web process."""
    return request.app.state.repo_root


def template_context(request: Request, **values: Any) -> dict[str, Any]:
    """Build common template context."""
    return {
        "request": request,
        "repo_root": str(repo_root(request)),
        **values,
    }
