"""Lambda events that aren't HTTP requests: migrations, the janitor, house runs, keep-warm pings
and deploy health checks.

The Lambda Web Adapter forwards non-HTTP invocations (EventBridge Scheduler, ``aws lambda
invoke``) to ``POST /events``. It sets ``x-amzn-request-context`` on every request, replacing
any the caller sent: the event's request context as JSON for HTTP events (a Function URL
request), and ``null`` for these pass-through invocations. Requests with a real context are
refused here, and CloudFront never routes ``/events``. So only callers allowed to invoke the
function (IAM) reach these tasks.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from arena.db.migrate import grant_app_role, migrate
from arena.engine.spec import ENGINE_VERSION, SEASON

router = APIRouter(include_in_schema=False)
log = logging.getLogger("arena.events")


class Event(BaseModel, extra="allow"):
    task: str


def _over_http(request: Request) -> bool:
    raw = request.headers.get("x-amzn-request-context")
    if raw is None:
        return False  # not behind the adapter: local runs and tests
    try:
        return json.loads(raw) is not None
    except ValueError:
        return True


@router.post("/events")
def events(event: Event, request: Request) -> dict[str, Any]:
    if _over_http(request):
        raise HTTPException(403, "tasks can't be triggered over HTTP")
    state = request.app.state
    settings = state.settings
    if event.task == "warm":
        return {"ok": True}
    if event.task == "health":
        # A deploy invokes a newly published version with this before moving traffic to it.
        with state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "build": settings.build, "engine": ENGINE_VERSION}
    if settings.role == "api":
        raise HTTPException(403, f"the api function doesn't run {event.task!r}")
    params = event.model_extra or {}
    log.info("task %s %s", event.task, params)
    if event.task == "migrate":
        applied = migrate(state.engine, dsql=settings.db == "dsql")
        if settings.db == "dsql" and settings.dsql_app_role_arn:
            grant_app_role(state.engine, settings.dsql_user, settings.dsql_app_role_arn)
        return {"ok": True, "applied": applied, "engine": ENGINE_VERSION}
    if event.task == "audit":
        from arena.services.audit import audit

        return audit(state.engine, str(params.get("season", SEASON)))
    if event.task == "janitor":
        return {"ok": True, "ended": state.episodes.janitor(settings.idle_timeout_s)}
    if event.task == "house":
        from arena.house import run_house

        summary = run_house(
            state.episodes,
            str(params.get("agent", "random")),
            int(params.get("episodes", 100)),
            track=str(params.get("track", "red-1")),
            seed=int(params.get("seed", 0)),
        )
        return {"ok": True, **summary}
    raise HTTPException(400, f"unknown task {event.task!r}")
