"""``evaluate()``: play an exact number of Arena episodes, in batches, and summarise them.

The chooser has the signature of ``examples/balatro_sb3.py``'s choosers in the jackdaw repo,
``choose(envs, batch_obs, masks) -> actions``, so the same function evaluates locally and
here. ``model_chooser(MaskablePPO.load(...))`` works unchanged. ``envs`` holds one handle
per episode (its ``id`` and ``t``); there is no local run to read.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from jackdaw_arena.client import ArenaClient


@dataclass
class Handle:
    id: str
    t: int
    n_actions: int
    obs: dict[str, np.ndarray]
    reward: float = 0.0


@dataclass(frozen=True)
class EpisodeResult:
    id: str
    seed: str
    ante_reached: int
    blinds_beaten: int
    won: bool
    reward: float
    length: int
    truncated: bool
    refused: bool
    verified: bool
    end_reason: str


@dataclass
class Evaluation:
    results: list[EpisodeResult] = field(default_factory=list)

    def summary(self) -> dict[str, float]:
        """The fields ``examples/balatro_sb3.summarize`` reports, plus the SEM. A refused
        episode (an env bug) scores zero, as there."""
        r = self.results
        if not r:
            return {"episodes": 0.0}
        blinds = np.array([0 if e.refused else e.blinds_beaten for e in r], dtype=float)
        return {
            "episodes": float(len(r)),
            "ante_reached": float(np.mean([0 if e.refused else e.ante_reached for e in r])),
            "blinds_beaten": float(blinds.mean()),
            "blinds_beaten_sem": float(blinds.std(ddof=1) / np.sqrt(len(r))) if len(r) > 1 else 0.0,
            "win_rate": float(np.mean([e.won and not e.refused for e in r])),
            "reward": float(np.mean([e.reward for e in r])),
            "length": float(np.mean([e.length for e in r])),
            "truncated": float(np.mean([e.truncated for e in r])),
            "refused": float(sum(e.refused for e in r)),
            "max_ante": float(max(0 if e.refused else e.ante_reached for e in r)),
            "verified": float(all(e.verified for e in r)),
        }


Chooser = Callable[[list[Handle], dict[str, np.ndarray], np.ndarray], Sequence[int]]


def random_chooser(seed: int = 0) -> Chooser:
    rng = np.random.default_rng(seed)

    def choose(envs: list[Handle], obs: dict[str, np.ndarray], masks: np.ndarray) -> list[int]:
        return [int(rng.choice(np.flatnonzero(m))) for m in masks]

    return choose


def evaluate(
    choose: Chooser,
    episodes: int,
    *,
    track: str = "red-1",
    reward: str = "sparse",
    batch: int = 32,
    client: ArenaClient | None = None,
    progress: bool = True,
) -> Evaluation:
    """Play ``episodes`` episodes, ``batch`` at a time, and return their results.

    Episodes this agent left running (an interrupted run) are adopted first, so no budget is
    lost. Only as many new episodes are started as are needed, and every started episode is
    played to its end.
    """
    client = client or ArenaClient()
    spec = client.spec()
    out = Evaluation()
    active: dict[str, Handle] = {}

    for r in [r for r in client.running() if r["track"] == track][:episodes]:
        state = client.get(r["id"])
        if state["status"] == "running":
            active[r["id"]] = Handle(
                r["id"], state["t"], state["n_actions"], spec.decode(state["obs"])
            )
    to_start = episodes - len(active)

    def record(eid: str, h: Handle, step: dict[str, Any] | None, final: dict[str, Any]) -> None:
        out.results.append(
            EpisodeResult(
                id=eid,
                seed=final["seed"],
                ante_reached=int(final["ante_reached"] or 0),
                blinds_beaten=int(final["rounds_beaten"] or 0),
                won=bool(final["won"]),
                reward=h.reward,
                length=int(final["length"]),
                truncated=bool(step["truncated"]) if step else final["end_reason"] != "won",
                refused=final.get("refused") is not None,
                verified=bool(final["verified"]),
                end_reason=final["end_reason"],
            )  # fmt: skip
        )
        if progress:
            print(f"\r{len(out.results)}/{episodes} episodes", end="", file=sys.stderr, flush=True)

    while active or to_start > 0:
        if len(active) < batch and to_start > 0:
            n = min(batch - len(active), to_start, 64)
            keys = [str(uuid.uuid4()) for _ in range(n)]
            for ep in client.create(n, track, reward, keys=keys):
                if ep["status"] == "running":
                    active[ep["id"]] = Handle(
                        ep["id"], ep["t"], ep["n_actions"], spec.decode(ep["obs"])
                    )
                elif ep.get("final"):
                    record(ep["id"], Handle(ep["id"], ep["t"], 0, {}), None, ep["final"])
            to_start -= n
        if not active:
            continue
        ids = list(active)
        handles = [active[i] for i in ids]
        obs = {k: np.stack([h.obs[k] for h in handles]) for k in handles[0].obs}
        masks = np.stack([spec.mask(h.n_actions) for h in handles])
        actions = [int(a) for a in np.asarray(choose(handles, obs, masks)).reshape(-1)]
        steps = [(i, active[i].t, a) for i, a in zip(ids, actions, strict=True)]
        for i, r in zip(ids, client.step(steps), strict=True):
            h = active[i]
            if r["ok"]:
                h.reward += float(r["reward"])
                if r["final"] is not None:
                    record(i, h, r, r["final"])
                    del active[i]
                else:
                    h.t, h.n_actions, h.obs = r["t"], r["n_actions"], spec.decode(r["obs"])
            elif r["error"] == "ended":
                record(i, h, None, r.get("final") or client.get(i)["final"])
                del active[i]
            elif r["error"] == "conflict":
                state = client.get(i)  # another process moved it on: resync
                if state["status"] == "running":
                    h.t, h.n_actions = state["t"], state["n_actions"]
                    h.obs = spec.decode(state["obs"])
                else:
                    record(i, h, None, state["final"])
                    del active[i]
            else:
                raise RuntimeError(f"step refused for {i}: {r}")
    if progress:
        print(file=sys.stderr)
    return out
