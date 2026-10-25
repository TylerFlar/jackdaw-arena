"""Who is calling: an agent (bearer token, ``/api/v1``) or a signed-in user (session cookie)."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from arena.auth.tokens import TOKEN_PREFIX, digest
from arena.db import repo

_bearer = HTTPBearer(auto_error=False, description="An agent token: jdk_...")


def current_agent(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> repo.Agent:
    """The agent a ``Bearer jdk_...`` token belongs to. Cookies are never consulted here, so a
    page can't make a signed-in browser act as an agent."""
    if credentials is None or not credentials.credentials.startswith(TOKEN_PREFIX):
        raise HTTPException(401, "an agent token (Authorization: Bearer jdk_...) is required")
    state = request.app.state
    now = state.clock()
    with state.engine.connect() as conn:
        found = repo.agent_for_token(conn, digest(credentials.credentials))
        if found is None:
            raise HTTPException(401, "unknown or revoked token")
        # Record use at most hourly: a write per request would cost more than the request.
        if found.last_used_at is None or now - found.last_used_at > timedelta(hours=1):
            repo.touch_token(conn, found.token_id, now)
            conn.commit()
    return found.agent


def optional_user(request: Request) -> repo.User | None:
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie)
    if not token:
        return None
    with request.app.state.engine.connect() as conn:
        return repo.session_user(conn, digest(token), request.app.state.clock())


def current_user(user: Annotated[repo.User | None, Depends(optional_user)]) -> repo.User:
    if user is None:
        raise HTTPException(401, "sign in first")
    return user


def csrf_protect(request: Request) -> None:
    """For cookie-authenticated changes. Browsers send ``Origin`` with every cross-site request,
    and a custom header forces a CORS preflight that this API never answers. So a forged
    cross-site form or fetch fails both checks."""
    origin = request.headers.get("origin")
    if origin is not None and origin != request.app.state.settings.public_origin:
        raise HTTPException(403, "cross-origin request refused")
    if request.headers.get("x-arena-csrf") != "1":
        raise HTTPException(403, "missing X-Arena-CSRF header")


AgentDep = Annotated[repo.Agent, Depends(current_agent)]
UserDep = Annotated[repo.User, Depends(current_user)]
OptionalUserDep = Annotated[repo.User | None, Depends(optional_user)]
