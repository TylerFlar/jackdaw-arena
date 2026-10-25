"""Request and response models. They define the OpenAPI document, which the web app's TypeScript
types are generated from."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_serializer

# --- agent protocol ----------------------------------------------------------------------------


class Reward(BaseModel):
    kind: Literal["sparse", "blind_progress", "shaped"] = "sparse"
    weights: dict[str, float] | None = Field(
        None, description="ShapedReward weights to override (shaped only)"
    )


class EpisodeCreate(BaseModel):
    track: str = "red-1"
    keys: list[uuid.UUID] = Field(
        min_length=1,
        max_length=64,
        description="One idempotency key per episode: resending a key returns its episode",
    )
    reward: Reward = Reward()


class Final(BaseModel):
    """How an episode ended. The seeds are revealed once it has."""

    end_reason: str
    won: bool | None
    ante_reached: int | None
    rounds_beaten: int | None
    length: int
    seed: str
    rng_seed: int
    final_state_hash: str | None
    verified: bool | None
    refused: str | None = None
    not_ported: str | None = None

    @field_serializer("rng_seed")
    def _rng_seed(self, v: int) -> str:
        return str(v)  # a 63-bit integer doesn't survive a JavaScript number


class EpisodeState(BaseModel):
    id: uuid.UUID
    key: uuid.UUID
    status: str
    t: int
    obs: str | None = Field(description="base64 of 614 little-endian float32 values")
    n_actions: int = Field(description="the first n of the Discrete(500) actions are legal")
    final: Final | None = None


class EpisodesCreated(BaseModel):
    episodes: list[EpisodeState]


class LastStep(BaseModel):
    t: int
    action: int
    reward: float
    terminated: bool
    truncated: bool


class EpisodeResume(EpisodeState):
    last: LastStep | None = None


class StepItem(BaseModel):
    id: uuid.UUID
    t: int = Field(ge=0, description="the episode's step count before this action")
    action: int = Field(ge=0, lt=65536)


class StepRequest(BaseModel):
    steps: list[StepItem] = Field(min_length=1, max_length=256)


class StepOutcome(BaseModel):
    id: uuid.UUID
    ok: bool
    t: int | None = None
    obs: str | None = None
    n_actions: int | None = None
    reward: float | None = None
    terminated: bool | None = None
    truncated: bool | None = None
    final: Final | None = None
    error: Literal["conflict", "illegal_action", "ended", "not_found"] | None = None


class StepResponse(BaseModel):
    results: list[StepOutcome]


class RunningEpisode(BaseModel):
    id: uuid.UUID
    key: uuid.UUID
    t: int
    track: str


class AgentMe(BaseModel):
    agent: str
    name: str
    owner: str | None
    running: int
    used: dict[str, int] = Field(description="episodes started per track this season")
    season: str


class Error(BaseModel):
    error: str
    message: str
    detail: Any = None


# --- public site -------------------------------------------------------------------------------


class Owner(BaseModel):
    login: str | None
    avatar_url: str | None


class AgentSummary(BaseModel):
    slug: str
    name: str
    description: str
    url: str | None
    kind: str
    owner: Owner
    created_at: datetime


class Stats(BaseModel):
    n: int
    blinds_mean: float
    blinds_sem: float | None
    blinds_ci95: tuple[float, float] | None
    ante_mean: float
    max_ante: int
    win_rate: float
    win_ci95: tuple[float, float]
    length_mean: float
    truncated: float
    forfeited: float
    unverified: int


class BoardRow(BaseModel):
    rank: int | None
    agent: AgentSummary
    stats: Stats


class Leaderboard(BaseModel):
    track: str
    season: str
    k: int
    ranked: list[BoardRow]
    provisional: list[BoardRow]
    house: list[BoardRow]


class TrackInfo(BaseModel):
    key: str
    name: str
    back: str
    stake: int
    max_steps: int
    end_on_win: bool
    max_free_moves: int | None
    episodes_per_agent: int


class EpisodeSummary(BaseModel):
    id: uuid.UUID
    agent: str
    track: str
    season: str
    status: str
    t: int
    created_at: datetime
    ended_at: datetime | None
    final: Final | None = None


class AgentPage(BaseModel):
    agent: AgentSummary
    season: str
    tracks: dict[str, Stats | None]
    histogram: dict[str, list[int]] = Field(description="episodes by blinds beaten, per track")
    recent: list[EpisodeSummary]


class EpisodePage(BaseModel):
    episodes: list[EpisodeSummary]
    next: str | None = Field(None, description="cursor for the next page")
