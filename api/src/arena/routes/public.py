"""The public read API behind the website. No cookies are read here, so CloudFront can cache
every response. Ended episodes are immutable."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import anyio
from fastapi import APIRouter, HTTPException, Query, Request, Response

from arena import schemas
from arena.db import repo
from arena.engine.catalog import catalog
from arena.engine.frames import frames
from arena.engine.spec import ENGINE_VERSION
from arena.services.episodes import final_of
from arena.services.leaderboard import agent_summary, agent_tracks, leaderboard

router = APIRouter(prefix="/api", tags=["public"])

IMMUTABLE = "public, max-age=31536000, immutable"


def _cache(response: Response, seconds: int) -> None:
    """Cache at the edge (CloudFront) for ``seconds``, but not in browsers: a researcher who just
    finished a run should see it on the next page load, not a minute later."""
    response.headers["Cache-Control"] = f"public, max-age=0, s-maxage={seconds}"


def visible(agent: repo.Agent | None) -> bool:
    return agent is not None and not agent.hidden and not agent.unlisted


def episode_summary(row: repo.EpisodeRow, slug: str) -> dict[str, Any]:
    return {
        "id": row.id, "agent": slug, "track": row.track, "season": row.season,
        "status": row.status, "t": row.t, "created_at": row.created_at, "ended_at": row.ended_at,
        "final": final_of(row) if row.status == "ended" else None,
    }  # fmt: skip


def tape_document(row: repo.EpisodeRow) -> dict[str, Any]:
    """Everything needed to re-verify an ended episode with jackdaw alone."""
    return {
        "format": "jackdaw-arena.tape/1", "id": str(row.id), "engine_version": row.season,
        "action_version": row.action_version, "track": row.track, "back": row.back,
        "stake": row.stake, "seed": row.seed, "rng_seed": str(row.rng_seed),
        "max_steps": row.max_steps, "end_on_win": row.end_on_win,
        "max_free_moves": row.max_free_moves, "reward": row.reward_kind,
        "indices": row.indices, "tape": row.tape or [], "attempted": row.attempted,
        "final_state_hash": row.final_state_hash, "verified": row.verified,
        "end_reason": row.end_reason,
    }  # fmt: skip


async def frames_document(row: repo.EpisodeRow, start: int, limit: int) -> dict[str, Any]:
    if row.season != ENGINE_VERSION:
        raise HTTPException(409, f"replays of engine {row.season} episodes aren't served yet")
    tape = row.tape or []
    # Replaying is CPU work: keep it off the event loop.
    out = await anyio.to_thread.run_sync(frames, row.spec, tape, start, limit)
    return {"total": len(tape) + 1, "start": start, "frames": out}


@router.get("/tracks", response_model=list[schemas.TrackInfo])
def tracks(request: Request, response: Response) -> list[dict[str, Any]]:
    with request.app.state.engine.connect() as conn:
        out = [t.public() for t in repo.list_tracks(conn)]
    _cache(response, 300)
    return out


@router.get("/leaderboard", response_model=schemas.Leaderboard)
def get_leaderboard(
    request: Request, response: Response, track: str = "red-1", season: str = ENGINE_VERSION
) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        t = repo.get_track(conn, track)
        if t is None:
            raise HTTPException(404, f"no track {track!r}")
        board = leaderboard(conn, t, season)
    _cache(response, 60)
    return board


@router.get("/agents/{slug}", response_model=schemas.AgentPage)
def agent_page(request: Request, response: Response, slug: str) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        agent = repo.agent_by_slug(conn, slug)
        if not visible(agent):
            raise HTTPException(404, "no such agent")
        assert agent is not None
        page = agent_document(conn, agent)
    _cache(response, 60)
    return page


def agent_document(conn: Any, agent: repo.Agent) -> dict[str, Any]:
    stats, hist = agent_tracks(conn, agent.id, repo.list_tracks(conn), ENGINE_VERSION)
    recent = repo.ended_episodes_of(conn, agent.id, None, None, 10)
    return {
        "agent": agent_summary(agent),
        "season": ENGINE_VERSION,
        "tracks": stats,
        "histogram": hist,
        "recent": [episode_summary(r, agent.slug) for r in recent],
    }


def episode_page(conn: Any, agent: repo.Agent, track: str | None, before: str | None,
                 limit: int) -> dict[str, Any]:  # fmt: skip
    cursor = datetime.fromisoformat(before) if before else None
    rows = repo.ended_episodes_of(conn, agent.id, track, cursor, limit + 1)
    page, more = rows[:limit], len(rows) > limit
    return {
        "episodes": [episode_summary(r, agent.slug) for r in page],
        "next": page[-1].ended_at.isoformat() if more and page[-1].ended_at else None,
    }


@router.get("/agents/{slug}/episodes", response_model=schemas.EpisodePage)
def agent_episodes(
    request: Request,
    response: Response,
    slug: str,
    track: str | None = None,
    before: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        agent = repo.agent_by_slug(conn, slug)
        if not visible(agent):
            raise HTTPException(404, "no such agent")
        assert agent is not None
        page = episode_page(conn, agent, track, before, limit)
    _cache(response, 30)
    return page


def _public_episode(request: Request, episode_id: uuid.UUID) -> tuple[repo.EpisodeRow, repo.Agent]:
    with request.app.state.engine.connect() as conn:
        row = repo.get_episode(conn, episode_id)
        agent = repo.agent_by_id(conn, row.agent_id) if row else None
    if row is None or not visible(agent) or row.status == "void":
        raise HTTPException(404, "no such episode")
    assert agent is not None
    return row, agent


@router.get("/episodes/{episode_id}", response_model=schemas.EpisodeSummary)
def episode(request: Request, response: Response, episode_id: uuid.UUID) -> dict[str, Any]:
    row, agent = _public_episode(request, episode_id)
    if row.status == "ended":
        response.headers["Cache-Control"] = IMMUTABLE
    else:
        _cache(response, 5)
    return episode_summary(row, agent.slug)


@router.get("/episodes/{episode_id}/frames", response_model=schemas.FramesDoc)
async def episode_frames(
    request: Request,
    response: Response,
    episode_id: uuid.UUID,
    start: int = Query(0, ge=0, alias="from"),
    limit: int = Query(200, ge=1, le=200),
) -> dict[str, Any]:
    row, _ = await anyio.to_thread.run_sync(_public_episode, request, episode_id)
    if row.status != "ended":
        raise HTTPException(404, "replays open once the episode has ended")
    doc = await frames_document(row, start, limit)
    response.headers["Cache-Control"] = IMMUTABLE
    return doc


@router.get("/episodes/{episode_id}/tape", response_model=schemas.TapeDoc)
def episode_tape(request: Request, response: Response, episode_id: uuid.UUID) -> dict[str, Any]:
    row, _ = _public_episode(request, episode_id)
    if row.status != "ended":
        raise HTTPException(404, "the tape is published once the episode has ended")
    response.headers["Cache-Control"] = IMMUTABLE
    return tape_document(row)


@router.get("/catalog", response_model=schemas.Catalog)
def get_catalog(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=86400"
    return {"engine_version": ENGINE_VERSION, **catalog()}
