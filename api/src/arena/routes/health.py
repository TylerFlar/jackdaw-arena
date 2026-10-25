from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from arena import __version__
from arena.engine.spec import ENGINE_VERSION

router = APIRouter(tags=["health"])


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """Liveness, with no database round trip: the Lambda Web Adapter polls this at start-up."""
    return {"status": "ok"}


@router.get("/healthz/deep", include_in_schema=False)
def deep(request: Request) -> Any:
    try:
        with request.app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - report any database failure as unhealthy
        return JSONResponse({"status": "db_unavailable"}, status_code=503)
    return {"status": "ok"}


@router.get("/api/version", tags=["public"])
def version(request: Request) -> dict[str, str]:
    return {
        "arena": __version__,
        "engine": ENGINE_VERSION,
        "build": request.app.state.settings.build,
    }
