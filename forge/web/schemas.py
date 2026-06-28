"""Shared web response helpers."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def success(data: Any = None) -> dict[str, Any]:
    """Return the standard API success envelope."""
    return {"ok": True, "data": {} if data is None else data}


def error_response(
    message: str, *, type_name: str = "error", status_code: int = 400
) -> JSONResponse:
    """Return the standard API error envelope."""
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": {"message": message, "type": type_name}},
    )
