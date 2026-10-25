"""The agent protocol (``/api/v1``): what an agent's client speaks, authenticated by token."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from arena import schemas
from arena.auth.deps import AgentDep
from arena.db import repo
from arena.engine.spec import spec_document
from arena.services.episodes import EpisodeService, StepItem

router = APIRouter(prefix="/api/v1", tags=["agent"])


def _service(request: Request) -> EpisodeService:
    return request.app.state.episodes


@router.get("/spec", summary="The engine, observation layout, actions, rewards and tracks")
def spec(request: Request) -> dict[str, Any]:
    state = request.app.state
    with state.engine.connect() as conn:
        tracks = [t.public() for t in repo.list_tracks(conn)]
    s = state.settings
    limits = {
        "max_running_per_agent": s.max_running_per_agent,
        "max_batch": s.max_batch,
        "max_new_episodes": s.max_new_episodes,
        "idle_timeout_s": s.idle_timeout_s,
    }
    return spec_document(tracks, limits)


@router.get("/me", response_model=schemas.AgentMe)
def me(request: Request, agent: AgentDep) -> dict[str, Any]:
    service = _service(request)
    with request.app.state.engine.connect() as conn:
        running = repo.count_running(conn, agent.id)
        used = repo.quota_used(conn, agent.id)
    return {
        "agent": agent.slug, "name": agent.name, "owner": agent.owner_login, "running": running,
        "used": {track: n for (track, season), n in used.items() if season == service.season},
        "season": service.season,
    }  # fmt: skip


@router.post(
    "/episodes",
    status_code=201,
    response_model=schemas.EpisodesCreated,
    responses={403: {"model": schemas.Error}, 429: {"model": schemas.Error}},
)
def create_episodes(
    body: schemas.EpisodeCreate, request: Request, agent: AgentDep
) -> dict[str, Any]:
    episodes = _service(request).create(
        agent, body.track, body.keys, body.reward.kind, body.reward.weights
    )
    return {"episodes": episodes}


@router.post("/step", response_model=schemas.StepResponse)
def step(body: schemas.StepRequest, request: Request, agent: AgentDep) -> dict[str, Any]:
    items = [StepItem(s.id, s.t, s.action) for s in body.steps]
    return {"results": _service(request).step(agent, items)}


@router.get("/episodes", response_model=list[schemas.RunningEpisode])
def running(
    request: Request, agent: AgentDep, status: Literal["running"] = "running"
) -> list[dict[str, Any]]:
    return _service(request).running(agent)


@router.get("/episodes/{episode_id}", response_model=schemas.EpisodeResume)
def get_episode(episode_id: uuid.UUID, request: Request, agent: AgentDep) -> dict[str, Any]:
    return _service(request).get(agent, episode_id)


@router.post("/episodes/{episode_id}/forfeit", response_model=schemas.Final)
def forfeit(episode_id: uuid.UUID, request: Request, agent: AgentDep) -> Any:
    final = _service(request).forfeit(agent, episode_id)
    return JSONResponse(schemas.Final(**final).model_dump(mode="json"))
