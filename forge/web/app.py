"""FastAPI app factory for the local Forge web UI."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from forge.project.resolver import resolve_root
from forge.web.routes import (
    artifacts,
    dashboard,
    execution,
    memory,
    patches,
    planning,
    project,
    repository,
    workflows,
    worksets,
)
from forge.web.schemas import error_response

_WEB_DIR = Path(__file__).parent


def create_app(root: Path | str | None = None) -> FastAPI:
    """Create a local-only Forge web application."""
    root = root or os.environ.get("FORGE_WEB_ROOT")
    resolved = resolve_root(override=root)
    app = FastAPI(title="Forge Web UI")
    app.state.repo_root = resolved.root
    app.state.git_detected = resolved.git_detected
    app.state.templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")
    app.include_router(dashboard.router)
    app.include_router(workflows.router)
    app.include_router(project.router)
    app.include_router(repository.router)
    app.include_router(worksets.router)
    app.include_router(planning.router)
    app.include_router(execution.router)
    app.include_router(artifacts.router)
    app.include_router(patches.router)
    app.include_router(memory.router)

    @app.exception_handler(Exception)
    async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
        return error_response(str(exc), type_name=exc.__class__.__name__, status_code=500)

    return app
