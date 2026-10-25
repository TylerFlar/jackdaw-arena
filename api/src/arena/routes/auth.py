"""``/auth``: sign in with a provider, sign out."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse

from arena import schemas
from arena.auth.deps import OptionalUserDep, csrf_protect
from arena.auth.oauth import HANDSHAKE_COOKIE, HANDSHAKE_MAX_AGE, SignIn, SignInError
from arena.auth.tokens import digest
from arena.db import repo

router = APIRouter(prefix="/auth", tags=["auth"])


def _signin(request: Request) -> SignIn:
    return request.app.state.signin


@router.get("/providers", response_model=list[schemas.Provider])
def providers(request: Request) -> list[dict[str, str]]:
    return _signin(request).listing()


@router.get("/session", response_model=schemas.Session)
def session(response: Response, user: OptionalUserDep) -> dict[str, Any]:
    """Who is signed in, if anyone. Always 200, so pages can ask without logging an error."""
    response.headers["Cache-Control"] = "no-store"
    return {"user": user_json(user) if user else None}


@router.get("/login/{provider}", include_in_schema=False)
def login(provider: str, request: Request, next: str = "/") -> Response:  # noqa: A002
    settings = request.app.state.settings
    try:
        url, cookie = _signin(request).begin(provider, next)
    except SignInError as exc:
        return RedirectResponse(f"/signin?error={quote(str(exc))}", status_code=303)
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(
        HANDSHAKE_COOKIE, cookie, max_age=HANDSHAKE_MAX_AGE, path="/auth", httponly=True,
        secure=settings.cookie_secure, samesite="lax",
    )  # fmt: skip
    return response


@router.get("/callback/{provider}", include_in_schema=False)
def callback(
    provider: str, request: Request, code: str | None = None, state: str | None = None
) -> Response:
    app = request.app.state
    settings = app.settings
    try:
        identity, next_path = _signin(request).finish(
            provider, code, state, request.cookies.get(HANDSHAKE_COOKIE)
        )
    except SignInError as exc:
        response: Response = RedirectResponse(f"/signin?error={quote(str(exc))}", status_code=303)
        response.delete_cookie(HANDSHAKE_COOKIE, path="/auth")
        return response
    admins = {login.lower() for login in settings.admin_logins}
    now = app.clock()
    token = secrets.token_urlsafe(32)
    with app.engine.begin() as conn:
        user = repo.upsert_identity_user(
            conn, identity.provider, identity.subject, identity.login, identity.name,
            identity.avatar_url, identity.provider == "github" and identity.login.lower() in admins,
            now,
        )  # fmt: skip
        # A fresh session id on every sign-in: nothing set before sign-in carries over.
        repo.create_session(
            conn, digest(token), user.id, now, now + timedelta(days=settings.session_days)
        )
    response = RedirectResponse(next_path, status_code=303)
    response.delete_cookie(HANDSHAKE_COOKIE, path="/auth")
    response.set_cookie(
        settings.session_cookie, token, max_age=settings.session_days * 86400, path="/",
        httponly=True, secure=settings.cookie_secure, samesite="lax",
    )  # fmt: skip
    return response


@router.post("/logout", status_code=204, dependencies=[Depends(csrf_protect)])
def logout(request: Request) -> Response:
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie)
    if token:
        with request.app.state.engine.begin() as conn:
            repo.delete_session(conn, digest(token))
    response = Response(status_code=204)
    response.delete_cookie(settings.session_cookie, path="/", secure=settings.cookie_secure)
    return response


def user_json(user: repo.User) -> dict[str, Any]:
    return {
        "login": user.login,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "is_admin": user.is_admin,
    }
