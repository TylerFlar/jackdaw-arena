"""The agent protocol's logic: start episodes, step them in batches, resume, forfeit.

Each process (one Lambda environment, or a local uvicorn) keeps live episodes in an LRU cache.
The database is the source of truth. Every step commits only if the stored ``t`` still matches,
so two processes stepping the same episode can't both succeed. A cache entry that disagrees with
a request is rebuilt from the database, which replays exactly. Responses go out only after the
commit, so an agent never sees a state the database doesn't have.
"""

from __future__ import annotations

import base64
import threading
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from jackdaw.env.action_space import ACTION_VERSION
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from arena.clock import Clock
from arena.db import repo
from arena.db.engine import is_serialization_failure
from arena.engine.live import CorruptTrace, EnvFactory, LiveEpisode, Outcome, StepResult, gym_env
from arena.engine.spec import ENGINE_VERSION, reward_weights
from arena.services.seeds import SeedSource


class ProtocolError(Exception):
    """A request the protocol refuses as a whole."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class StepItem:
    id: uuid.UUID
    t: int
    action: int


@dataclass(frozen=True)
class Limits:
    max_running: int = 64
    max_batch: int = 256
    max_new: int = 64


def final_of(row: repo.EpisodeRow) -> dict[str, Any]:
    """An ended episode's outcome, as the protocol reports it. The seeds are revealed here."""
    return {
        "end_reason": row.end_reason, "won": row.won, "ante_reached": row.ante_reached,
        "rounds_beaten": row.rounds_beaten, "length": row.t, "seed": row.seed,
        "rng_seed": row.rng_seed, "final_state_hash": row.final_state_hash,
        "verified": row.verified, "refused": row.refused, "not_ported": row.not_ported,
    }  # fmt: skip


def _final(outcome: Outcome, live: LiveEpisode) -> dict[str, Any]:
    return {
        "end_reason": outcome.end_reason, "won": outcome.won,
        "ante_reached": outcome.ante_reached, "rounds_beaten": outcome.rounds_beaten,
        "length": outcome.length, "seed": live.spec.seed, "rng_seed": live.spec.rng_seed,
        "final_state_hash": outcome.final_state_hash, "verified": outcome.verified,
        "refused": outcome.refused, "not_ported": outcome.not_ported,
    }  # fmt: skip


def _ok(eid: uuid.UUID, r: StepResult, live: LiveEpisode) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": eid, "ok": True, "t": r.t, "obs": base64.b64encode(r.obs).decode("ascii"),
        "n_actions": r.n_actions, "reward": r.reward, "terminated": r.terminated,
        "truncated": r.truncated, "final": None,
    }  # fmt: skip
    if r.outcome is not None:
        out["final"] = _final(r.outcome, live)
    return out


def _err(eid: uuid.UUID, code: str, t: int | None = None, **extra: Any) -> dict[str, Any]:
    return {"id": eid, "ok": False, "error": code, "t": t, **extra}


class EpisodeService:
    def __init__(
        self,
        engine: Engine,
        clock: Clock,
        seeds: SeedSource,
        env_factory: EnvFactory = gym_env,
        cache_size: int = 512,
        limits: Limits | None = None,
        season: str = ENGINE_VERSION,
    ) -> None:
        self.engine, self.clock, self.seeds = engine, clock, seeds
        self.env_factory, self.cache_size, self.limits, self.season = (
            env_factory,
            cache_size,
            limits or Limits(),
            season,
        )
        # episode id -> (owning agent id, live episode). Lookups check the owner: a cached
        # episode is still only the agent's that started it.
        self._cache: OrderedDict[uuid.UUID, tuple[uuid.UUID, LiveEpisode]] = OrderedDict()
        # One lock per process: mutations here are microseconds; correctness across processes
        # comes from the database's conditional updates.
        self._lock = threading.RLock()

    # --- cache ----------------------------------------------------------------------------------

    def _get(self, eid: uuid.UUID, agent_id: uuid.UUID) -> LiveEpisode | None:
        entry = self._cache.get(eid)
        if entry is None or entry[0] != agent_id:
            return None
        self._cache.move_to_end(eid)
        return entry[1]

    def _put(self, eid: uuid.UUID, agent_id: uuid.UUID, live: LiveEpisode) -> None:
        if self.cache_size <= 0:
            return
        self._cache[eid] = (agent_id, live)
        self._cache.move_to_end(eid)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    def evict(self, eid: uuid.UUID) -> None:
        self._cache.pop(eid, None)

    def _rebuild(self, row: repo.EpisodeRow) -> LiveEpisode:
        if row.season != self.season:
            raise ProtocolError(
                409, "stale_season", f"episode {row.id} is from engine {row.season}"
            )
        try:
            return LiveEpisode.rebuild(row.spec, row.indices, self.env_factory)
        except CorruptTrace as exc:  # pragma: no cover - an engine change or a damaged row
            raise ProtocolError(
                500, "corrupt_episode", f"episode {row.id} does not replay: {exc}"
            ) from exc

    # --- create ---------------------------------------------------------------------------------

    def create(
        self,
        agent: repo.Agent,
        track_key: str,
        keys: Sequence[uuid.UUID],
        reward_kind: str = "sparse",
        weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Start one episode per idempotency key. Keys already used return their episode."""
        if not 1 <= len(keys) <= self.limits.max_new:
            raise ProtocolError(422, "bad_request", f"send 1 to {self.limits.max_new} keys")
        if len(set(keys)) != len(keys):
            raise ProtocolError(422, "bad_request", "keys must be distinct")
        try:
            weight_values = reward_weights(reward_kind, weights)
        except ValueError as exc:
            raise ProtocolError(422, "bad_reward", str(exc)) from None

        with self._lock:
            rows = self._create_rows(agent, track_key, keys, reward_kind, weight_values)
            out = []
            for key in keys:
                row = rows[key]
                if row.status != "running":
                    out.append({"id": row.id, "key": key, "status": row.status, "t": row.t,
                                "obs": None, "n_actions": 0, "final": final_of(row)})  # fmt: skip
                    continue
                live = self._get(row.id, agent.id)
                if live is None:
                    live = (
                        LiveEpisode.start(row.spec, self.env_factory)
                        if row.t == 0
                        else self._rebuild(row)
                    )
                    self._put(row.id, agent.id, live)
                out.append({
                    "id": row.id, "key": key, "status": "running", "t": live.t,
                    "obs": base64.b64encode(live.obs).decode("ascii"),
                    "n_actions": live.n_actions, "final": None,
                })  # fmt: skip
            return out

    def _create_rows(
        self,
        agent: repo.Agent,
        track_key: str,
        keys: Sequence[uuid.UUID],
        reward_kind: str,
        weight_values: tuple[float, ...] | None,
    ) -> dict[uuid.UUID, repo.EpisodeRow]:
        for attempt in range(3):
            try:
                with self.engine.begin() as conn:
                    track = repo.get_track(conn, track_key)
                    if track is None or not track.active:
                        raise ProtocolError(404, "unknown_track", f"no track {track_key!r}")
                    existing = {
                        r.client_key: r for r in repo.episodes_by_keys(conn, agent.id, keys)
                    }
                    new = [k for k in keys if k not in existing]
                    if new:
                        running = repo.count_running(conn, agent.id)
                        if running + len(new) > self.limits.max_running:
                            raise ProtocolError(
                                429, "too_many_running",
                                f"{running} episodes running; "
                                f"the limit is {self.limits.max_running}",
                            )  # fmt: skip
                        used = repo.reserve_quota(
                            conn, agent.id, track.key, self.season, len(new),
                            track.episodes_per_agent,
                        )  # fmt: skip
                        if used is None:
                            raise ProtocolError(
                                403, "budget_exhausted",
                                f"this agent has used its {track.episodes_per_agent} episodes "
                                f"on {track.key} this season",
                            )  # fmt: skip
                        now = self.clock()
                        fresh = []
                        for k in new:
                            seed, rng_seed = self.seeds()
                            fresh.append({
                                "id": uuid.uuid4(), "agent_id": agent.id, "track": track.key,
                                "client_key": k, "season": self.season,
                                "action_version": ACTION_VERSION, "seed": seed,
                                "rng_seed": rng_seed, "back": track.back, "stake": track.stake,
                                "max_steps": track.max_steps, "end_on_win": track.end_on_win,
                                "max_free_moves": track.max_free_moves, "reward_kind": reward_kind,
                                "reward_weights": list(weight_values) if weight_values else None,
                                "trace": b"", "now": now,
                            })  # fmt: skip
                        repo.insert_episodes(conn, fresh)
                        existing.update(
                            {r.client_key: r for r in repo.episodes_by_keys(conn, agent.id, new)}
                        )
                    return existing
            except IntegrityError:
                # A concurrent request used the same key (or, astronomically rarely, the same
                # seed). Try again: the keys now exist and come back as they are.
                if attempt == 2:
                    raise
            except DBAPIError as exc:
                if attempt == 2 or not is_serialization_failure(exc):
                    raise
        raise AssertionError("unreachable")

    # --- step -----------------------------------------------------------------------------------

    def step(self, agent: repo.Agent, items: Sequence[StepItem]) -> list[dict[str, Any]]:
        if not 1 <= len(items) <= self.limits.max_batch:
            raise ProtocolError(422, "bad_request", f"send 1 to {self.limits.max_batch} steps")
        if len({it.id for it in items}) != len(items):
            raise ProtocolError(422, "bad_request", "each episode may appear once per batch")
        with self._lock:
            for attempt in range(2):
                try:
                    return self._step(agent, items)
                except DBAPIError as exc:
                    # The whole batch lost a race (DSQL optimistic concurrency): nothing was
                    # committed. Drop what this process applied and replay from the database.
                    for it in items:
                        self.evict(it.id)
                    if attempt == 1 or not is_serialization_failure(exc):
                        raise
        raise AssertionError("unreachable")

    def _step(self, agent: repo.Agent, items: Sequence[StepItem]) -> list[dict[str, Any]]:
        def fresh_enough(it: StepItem, live: LiveEpisode | None) -> bool:
            if live is None:
                return False
            if it.t == live.t:
                return live.outcome is None
            return it.t == live.t - 1 and live.last is not None and live.last[0] == it.action

        lives: dict[uuid.UUID, LiveEpisode] = {}
        stale = []
        for it in items:
            cached = self._get(it.id, agent.id)
            if fresh_enough(it, cached):
                assert cached is not None
                lives[it.id] = cached
            else:
                stale.append(it.id)
        rows: dict[uuid.UUID, repo.EpisodeRow] = {}
        if stale:
            with self.engine.connect() as conn:
                rows = {r.id: r for r in repo.episodes_by_ids(conn, stale, agent.id)}
            for eid in stale:
                self.evict(eid)
                row = rows.get(eid)
                if row is not None and row.status == "running":
                    lives[eid] = self._rebuild(row)
                    self._put(eid, agent.id, lives[eid])

        results: dict[uuid.UUID, dict[str, Any]] = {}
        pending: list[tuple[StepItem, LiveEpisode, StepResult, int]] = []
        for it in items:
            live = lives.get(it.id)
            row = rows.get(it.id)
            if live is None:
                if row is None:
                    results[it.id] = _err(it.id, "not_found")
                elif row.status == "ended":
                    results[it.id] = self._ended(it, row)
                else:
                    results[it.id] = _err(it.id, "ended", row.t)
                continue
            if it.t == live.t - 1 and live.last is not None and live.last[0] == it.action:
                results[it.id] = _ok(it.id, live.last[1], live)  # a retry: the same response
            elif live.outcome is not None:
                results[it.id] = _err(it.id, "ended", live.t)
            elif it.t != live.t:
                results[it.id] = _err(it.id, "conflict", live.t)
            elif not 0 <= it.action < live.n_actions:
                results[it.id] = _err(it.id, "illegal_action", live.t, n_actions=live.n_actions)
            else:
                t_before = live.t
                pending.append((it, live, live.apply(it.action), t_before))

        if pending:
            now = self.clock()
            with self.engine.begin() as conn:
                steps = [
                    (it.id, t0, repo.pack_index(it.action))
                    for it, _, r, t0 in pending
                    if r.outcome is None
                ]
                advanced = repo.commit_steps(conn, steps, now)
                for it, live, r, t0 in pending:
                    if r.outcome is not None and repo.end_episode(
                        conn, it.id, t0, repo.pack_index(it.action), r.outcome, live.tape,
                        live.engine_error, now,
                    ):  # fmt: skip
                        advanced.add(it.id)
            for it, live, r, _ in pending:
                if it.id in advanced:
                    results[it.id] = _ok(it.id, r, live)
                else:
                    # Another process moved this episode on first: forget our copy and report
                    # where the database has it.
                    self.evict(it.id)
                    with self.engine.connect() as conn:
                        current = repo.get_episode(conn, it.id)
                    results[it.id] = _err(it.id, "conflict", current.t if current else None)
        return [results[it.id] for it in items]

    def _ended(self, it: StepItem, row: repo.EpisodeRow) -> dict[str, Any]:
        """A step for an episode that has ended. If it retries the step that ended it, answer
        with that step's response again, rebuilt by replay."""
        indices = row.indices
        if indices and it.t == row.t - 1 and indices[-1] == it.action:
            live = LiveEpisode.rebuild(row.spec, indices, self.env_factory)
            if live.last is not None and live.last[1].outcome is not None:
                ok = _ok(it.id, live.last[1], live)
                ok["final"] = final_of(row)
                return ok
        return _err(it.id, "ended", row.t, final=final_of(row))

    # --- read, forfeit, janitor -----------------------------------------------------------------

    def get(self, agent: repo.Agent, eid: uuid.UUID) -> dict[str, Any]:
        with self.engine.connect() as conn:
            rows = repo.episodes_by_ids(conn, [eid], agent.id)
        if not rows:
            raise ProtocolError(404, "not_found", "no such episode for this agent")
        row = rows[0]
        if row.status != "running":
            return {"id": row.id, "key": row.client_key, "status": row.status, "t": row.t,
                    "obs": None, "n_actions": 0, "last": None, "final": final_of(row)}  # fmt: skip
        with self._lock:
            live = self._get(eid, agent.id)
            if live is None or live.t != row.t:
                live = self._rebuild(row)
                self._put(eid, agent.id, live)
            last = None
            if live.last is not None:
                a, r = live.last
                last = {"t": r.t, "action": a, "reward": r.reward, "terminated": r.terminated,
                        "truncated": r.truncated}  # fmt: skip
            return {
                "id": row.id, "key": row.client_key, "status": "running", "t": live.t,
                "obs": base64.b64encode(live.obs).decode("ascii"), "n_actions": live.n_actions,
                "last": last, "final": None,
            }  # fmt: skip

    def running(self, agent: repo.Agent) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = repo.running_of(conn, agent.id)
        return [{"id": r.id, "key": r.client_key, "t": r.t, "track": r.track} for r in rows]

    def forfeit(self, agent: repo.Agent, eid: uuid.UUID) -> dict[str, Any]:
        with self._lock:
            for _ in range(3):
                with self.engine.connect() as conn:
                    rows = repo.episodes_by_ids(conn, [eid], agent.id)
                if not rows:
                    raise ProtocolError(404, "not_found", "no such episode for this agent")
                row = rows[0]
                if row.status != "running":
                    return final_of(row)  # already over: forfeiting is idempotent
                if self._end(row, "forfeit"):
                    with self.engine.connect() as conn:
                        ended = repo.get_episode(conn, eid)
                    assert ended is not None
                    return final_of(ended)
            raise ProtocolError(409, "conflict", "the episode kept moving; try again")

    def _end(self, row: repo.EpisodeRow, reason: str) -> bool:
        """End a running episode without a step (forfeit, idle). False if it moved on."""
        self.evict(row.id)
        live = self._rebuild(row)
        outcome = live.end(reason)
        with self.engine.begin() as conn:
            return repo.end_episode(
                conn, row.id, row.t, None, outcome, live.tape, None, self.clock()
            )

    def janitor(self, idle_s: int, limit: int = 200) -> int:
        """Forfeit episodes idle for over ``idle_s`` seconds; returns how many it ended."""
        from datetime import timedelta

        before = self.clock() - timedelta(seconds=idle_s)
        with self.engine.connect() as conn:
            rows = repo.idle_running(conn, before, limit)
        ended = 0
        with self._lock:
            for row in rows:
                if row.season != self.season:
                    continue
                if self._end(row, "idle"):
                    ended += 1
        return ended
