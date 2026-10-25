"""``/api/me``: the signed-in researcher's agents and tokens. Cookie-authenticated; every change
also passes the CSRF check."""

from __future__ import annotations

import re
import uuid
from typing import Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.exc import IntegrityError

from arena.auth.deps import UserDep, csrf_protect
from arena.auth.tokens import digest, display_prefix, new_token
from arena.db import repo
from arena.engine.spec import ENGINE_VERSION
from arena.routes.auth import user_json
from arena.routes.public import agent_document, episode_page, frames_document, tape_document
from arena.services.leaderboard import agent_summary

router = APIRouter(prefix="/api/me", tags=["account"])
admin = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(csrf_protect)])

SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38})[a-z0-9]$")


class AgentCreate(BaseModel):
    slug: str = Field(description="3-40 characters: lowercase letters, digits, hyphens")
    name: str = Field(min_length=1, max_length=60)
    description: str = Field("", max_length=500)
    url: HttpUrl | None = None
    unlisted: bool = False


class AgentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    description: str | None = Field(None, max_length=500)
    url: HttpUrl | None = None
    unlisted: bool | None = None


class TokenCreate(BaseModel):
    label: str = Field("", max_length=60)


def _owned(conn: Any, user: repo.User, slug: str) -> repo.Agent:
    agent = repo.agent_by_slug(conn, slug)
    if agent is None or agent.user_id != user.id:
        raise HTTPException(404, "no such agent of yours")
    return agent


def _agent_json(conn: Any, a: repo.Agent) -> dict[str, Any]:
    used = repo.quota_used(conn, a.id)
    return {
        **agent_summary(a),
        "unlisted": a.unlisted,
        "hidden": a.hidden,
        "tokens": repo.tokens_of(conn, a.id),
        "used": {t: n for (t, s), n in used.items() if s == ENGINE_VERSION},
    }


@router.get("")
def me(request: Request, user: UserDep) -> dict[str, Any]:
    s = request.app.state.settings
    with request.app.state.engine.connect() as conn:
        agents = [_agent_json(conn, a) for a in repo.agents_of(conn, user.id)]
    return {
        "user": user_json(user),
        "agents": agents,
        "limits": {"agents": s.max_agents_per_user, "tokens_per_agent": s.max_tokens_per_agent},
    }


@router.post("/agents", status_code=201, dependencies=[Depends(csrf_protect)])
def create_agent(body: AgentCreate, request: Request, user: UserDep) -> dict[str, Any]:
    s = request.app.state.settings
    if not SLUG.match(body.slug) or body.slug.startswith("house-"):
        raise HTTPException(422, "the slug must be 3-40 lowercase letters, digits and hyphens")
    try:
        with request.app.state.engine.begin() as conn:
            if len(repo.agents_of(conn, user.id)) >= s.max_agents_per_user:
                raise HTTPException(429, f"you can have {s.max_agents_per_user} agents")
            aid = repo.create_agent(
                conn, user.id, body.slug, body.name, body.description,
                str(body.url) if body.url else None, "user", body.unlisted,
                request.app.state.clock(),
            )  # fmt: skip
            agent = repo.agent_by_id(conn, aid)
            assert agent is not None
            return _agent_json(conn, agent)
    except IntegrityError:
        raise HTTPException(409, f"the slug {body.slug!r} is taken") from None


@router.patch("/agents/{slug}", dependencies=[Depends(csrf_protect)])
def update_agent(slug: str, body: AgentUpdate, request: Request, user: UserDep) -> dict[str, Any]:
    with request.app.state.engine.begin() as conn:
        agent = _owned(conn, user, slug)
        fields = body.model_dump(exclude_unset=True)
        if "url" in fields:
            fields["url"] = str(fields["url"]) if fields["url"] else None
        repo.update_agent(conn, agent.id, **fields)
        updated = repo.agent_by_id(conn, agent.id)
        assert updated is not None
        return _agent_json(conn, updated)


@router.post("/agents/{slug}/tokens", status_code=201, dependencies=[Depends(csrf_protect)])
def create_token(slug: str, body: TokenCreate, request: Request, user: UserDep) -> dict[str, Any]:
    s = request.app.state.settings
    token = new_token()
    with request.app.state.engine.begin() as conn:
        agent = _owned(conn, user, slug)
        if len(repo.tokens_of(conn, agent.id)) >= s.max_tokens_per_agent:
            raise HTTPException(429, f"an agent can have {s.max_tokens_per_agent} tokens")
        tid = repo.create_token(
            conn, agent.id, digest(token), display_prefix(token), body.label,
            request.app.state.clock(),
        )  # fmt: skip
    # The only time the token is ever shown.
    return {"id": tid, "token": token, "prefix": display_prefix(token), "label": body.label}


@router.delete("/tokens/{token_id}", status_code=204, dependencies=[Depends(csrf_protect)])
def revoke_token(token_id: uuid.UUID, request: Request, user: UserDep) -> Response:
    with request.app.state.engine.begin() as conn:
        mine = [a.id for a in repo.agents_of(conn, user.id)]
        if not repo.revoke_token(conn, token_id, mine, request.app.state.clock()):
            raise HTTPException(404, "no such token of yours")
    return Response(status_code=204)


# --- the owner's views: also unlisted agents ---------------------------------------------------


@router.get("/agents/{slug}")
def my_agent(slug: str, request: Request, user: UserDep) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        return agent_document(conn, _owned(conn, user, slug))


@router.get("/agents/{slug}/episodes")
def my_agent_episodes(
    slug: str,
    request: Request,
    user: UserDep,
    track: str | None = None,
    before: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        return episode_page(conn, _owned(conn, user, slug), track, before, limit)


def _my_ended(request: Request, user: repo.User, episode_id: uuid.UUID) -> repo.EpisodeRow:
    with request.app.state.engine.connect() as conn:
        row = repo.get_episode(conn, episode_id)
        agent = repo.agent_by_id(conn, row.agent_id) if row else None
    if row is None or agent is None or agent.user_id != user.id:
        raise HTTPException(404, "no such episode of yours")
    if row.status != "ended":
        raise HTTPException(404, "replays open once the episode has ended")
    return row


@router.get("/episodes/{episode_id}/frames")
async def my_frames(
    episode_id: uuid.UUID,
    request: Request,
    user: UserDep,
    start: int = Query(0, ge=0, alias="from"),
    limit: int = Query(200, ge=1, le=200),
) -> dict[str, Any]:
    row = await anyio.to_thread.run_sync(_my_ended, request, user, episode_id)
    return await frames_document(row, start, limit)


@router.get("/episodes/{episode_id}/tape")
def my_tape(episode_id: uuid.UUID, request: Request, user: UserDep) -> dict[str, Any]:
    return tape_document(_my_ended(request, user, episode_id))


# --- moderation --------------------------------------------------------------------------------


class Moderate(BaseModel):
    hidden: bool


@admin.post("/agents/{slug}")
def moderate(slug: str, body: Moderate, request: Request, user: UserDep) -> dict[str, Any]:
    if not user.is_admin:
        raise HTTPException(403, "admins only")
    with request.app.state.engine.begin() as conn:
        agent = repo.agent_by_slug(conn, slug)
        if agent is None:
            raise HTTPException(404, "no such agent")
        repo.update_agent(conn, agent.id, hidden=body.hidden)
    return {"slug": slug, "hidden": body.hidden}
