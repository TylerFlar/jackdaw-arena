"""What the engine exposes to agents: versions, the observation layout, actions and rewards.

Everything here mirrors ``jackdaw.env.BalatroGymnasiumEnv`` so a remote agent sees exactly what
a local one does. ``/api/v1/spec`` publishes it; the client builds its Gymnasium spaces from it.
"""

from __future__ import annotations

import base64
import sys
from dataclasses import dataclass, fields
from typing import Any

from jackdaw import _core
from jackdaw.env.action_space import ACTION_VERSION, FREE_ACTION_TYPES, ActionType
from jackdaw.env.rewards import ShapedReward
from jackdaw.env.rust_gym import ENTITY_INFO, GLOBAL_DIM

# The Gym env writes observations as native-endian float32; the wire format is "<f4".
if sys.byteorder != "little":  # pragma: no cover - every supported platform is little-endian
    raise ImportError("Jackdaw Arena serves little-endian float32 observations")

ENGINE_VERSION: str = _core.__version__


@dataclass(frozen=True)
class Season:
    """Results that compare with each other: the jackdaw releases that play the same game.

    A release joins a season when every ended episode of the season replays with it to the
    recorded final state. Deploys check this with the audit task when the engine changes."""

    key: str  # stored on every episode
    label: str
    engines: tuple[str, ...]


SEASONS: dict[str, Season] = {
    "0.2.0": Season("0.2.0", "Season 1", ("0.2.0", "0.2.1")),
}
SEASON: str = "0.2.0"

if ENGINE_VERSION not in SEASONS[SEASON].engines:
    raise ImportError(
        f"jackdaw {ENGINE_VERSION} isn't one of season {SEASON}'s releases "
        f"{SEASONS[SEASON].engines}. A release that plays the same game joins it in "
        "arena.engine.spec.SEASONS; one that changes the game starts a new season."
    )


def replayable(season: str) -> bool:
    """Whether the running engine replays this season's episodes exactly."""
    return season in SEASONS and ENGINE_VERSION in SEASONS[season].engines


OBS_LEN: int = _core.GYM_OBS_LEN
MAX_ACTIONS: int = _core.MAX_ACTIONS
OBS_DTYPE = "<f4"

REWARD_KINDS: tuple[str, ...] = ("sparse", "blind_progress", "shaped")
SHAPED_WEIGHTS: tuple[tuple[str, float], ...] = tuple(
    (f.name, float(f.default)) for f in fields(ShapedReward)
)


def obs_fields() -> list[dict[str, Any]]:
    """The observation's arrays in the flat float32 buffer: name, shape and element offset,
    in the order ``jackdaw.env.rust_gym`` lays them out."""
    out: list[dict[str, Any]] = [{"name": "global", "shape": [GLOBAL_DIM], "offset": 0}]
    offset = GLOBAL_DIM
    for name, count, dim in ENTITY_INFO:
        out.append({"name": name, "shape": [count, dim], "offset": offset})
        offset += count * dim
    out.append({"name": "entity_counts", "shape": [len(ENTITY_INFO)], "offset": offset})
    if offset + len(ENTITY_INFO) != OBS_LEN:  # pragma: no cover - guards a jackdaw upgrade
        raise ImportError("jackdaw's Gym observation layout changed")
    return out


def action_types() -> list[dict[str, Any]]:
    return [{"id": int(t), "name": t.name, "free": t in FREE_ACTION_TYPES} for t in ActionType]


def encode_obs(data: bytes | bytearray | memoryview) -> str:
    """One observation on the wire: base64 of the 614 little-endian float32 values."""
    return base64.b64encode(data).decode("ascii")


def reward_weights(kind: str, weights: dict[str, float] | None) -> tuple[float, ...] | None:
    """The eight ``ShapedReward`` weights ``_core.GymEnv`` takes, defaults filled in.

    Raises ``ValueError`` for an unknown kind or weight name, or weights on a kind without
    them.
    """
    if kind not in REWARD_KINDS:
        raise ValueError(f"unknown reward {kind!r}; expected one of {', '.join(REWARD_KINDS)}")
    if kind != "shaped":
        if weights:
            raise ValueError(f"reward {kind!r} takes no weights")
        return None
    names = {name for name, _ in SHAPED_WEIGHTS}
    unknown = set(weights or {}) - names
    if unknown:
        raise ValueError(f"unknown shaped-reward weights: {', '.join(sorted(unknown))}")
    given = weights or {}
    return tuple(float(given.get(name, default)) for name, default in SHAPED_WEIGHTS)


def spec_document(tracks: list[dict[str, Any]], limits: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "action_version": ACTION_VERSION,
        "obs": {"length": OBS_LEN, "dtype": OBS_DTYPE, "fields": obs_fields()},
        "max_actions": MAX_ACTIONS,
        "action_types": action_types(),
        "rewards": {
            "kinds": list(REWARD_KINDS),
            "shaped_weights": [{"name": n, "default": d} for n, d in SHAPED_WEIGHTS],
        },
        "tracks": tracks,
        "limits": limits,
    }
