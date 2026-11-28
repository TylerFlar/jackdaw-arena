"""Running episodes across a change of jackdaw release, as a deploy makes one: another release
continues an episode only if it rebuilds the step it was on to what the agent saw, and voids it
otherwise."""

from __future__ import annotations

import base64
import struct
import uuid
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import text

from arena.db import repo
from arena.engine.live import LiveEpisode, RunSpec, gym_env, view_digest
from arena.engine.spec import ENGINE_VERSION, SEASON
from arena.services.episodes import EpisodeService
from tests.conftest import bearer
from tests.test_protocol import add_track, create, play, step

OTHER = "9.9.9"


class Reordered:
    """A ``_core.GymEnv`` that lists each table's actions backwards: another release, whose table
    holds the same actions under other indices."""

    def __init__(self, env: Any) -> None:
        object.__setattr__(self, "_env", env)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._env, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._env, name, value)

    def _flip(self, i: int) -> int:
        return self._env.n_actions - 1 - i

    def action(self, i: int) -> Any:
        return self._env.action(self._flip(i))

    def action_table(self) -> list[Any]:
        return self._env.action_table()[::-1]

    def step(self, i: int, cut_refused: bool) -> Any:
        return self._env.step(self._flip(i), cut_refused)


def reordered(spec: RunSpec, max_steps: int) -> Reordered:
    return Reordered(gym_env(spec, max_steps))


def deploy(app: Any, factory: Any = gym_env, release: str = OTHER) -> EpisodeService:
    """Serve ``app`` from a fresh process of jackdaw ``release`` (nothing cached), as a deploy
    does."""
    old: EpisodeService = app.state.episodes
    app.state.episodes = EpisodeService(
        old.engine, old.clock, old.seeds, factory, cache_size=64, release=release
    )
    return app.state.episodes


def row_of(engine: Any, eid: str) -> repo.EpisodeRow:
    with engine.connect() as conn:
        row = repo.get_episode(conn, uuid.UUID(eid))
    assert row is not None
    return row


def used(engine: Any, agent: repo.Agent, track: str = "red-1") -> int:
    with engine.connect() as conn:
        return repo.quota_used(conn, agent.id)[(track, SEASON)]


def test_each_step_records_its_release_and_what_the_agent_saw(client, agents, engine):
    _, token = agents.agent()
    (ep,) = create(client, token)
    row = row_of(engine, ep["id"])
    first = LiveEpisode.start(row.spec)
    assert row.last_engine_version == row.engine_version == ENGINE_VERSION
    assert row.state_digest == first.digest()
    rng, t, n = np.random.default_rng(1), 0, ep["n_actions"]
    for _ in range(6):
        (r,) = step(client, token, (ep["id"], t, int(rng.integers(n))))
        t, n = r["t"], r["n_actions"]
        row = row_of(engine, ep["id"])
        live = LiveEpisode.rebuild(row.spec, row.steps)
        seen = view_digest(base64.b64decode(r["obs"]), live.env.action_table())
        assert row.last_engine_version == ENGINE_VERSION and row.state_digest == seen


def test_a_release_that_rebuilds_the_step_alike_continues_the_episode(app, agents, engine):
    """A release whose table is the same reads the agent's index as the action it chose: the
    episode goes on, as if one release had played it."""
    _, token = agents.agent()
    with TestClient(app) as client:
        (ep,) = create(client, token)
        (r,) = step(client, token, (ep["id"], 0, 0))
        deploy(app)
        (r2,) = step(client, token, (ep["id"], r["t"], 0))
        assert r2["ok"] and r2["t"] == 2, r2
        row = row_of(engine, ep["id"])
        assert row.status == "running" and row.last_engine_version == OTHER
        same = LiveEpisode.rebuild(row.spec, row.steps)
        assert base64.b64decode(r2["obs"]) == same.obs and row.state_digest == same.digest()


def test_a_release_that_reads_an_index_differently_voids_the_episode(app, agents, engine):
    """Another table: the agent's last index (and every one before it) may name another action.
    The episode ends without a result, leaves the board, and its episode goes back to the
    budget."""
    agent, token = agents.agent()
    with TestClient(app) as client:
        key = str(uuid.uuid4())
        r = client.post("/api/v1/episodes", json={"track": "red-1", "keys": [key]},
                        headers=bearer(token))  # fmt: skip
        (ep,) = r.json()["episodes"]
        (r,) = step(client, token, (ep["id"], 0, 0))
        before = used(engine, agent)
        deploy(app, reordered)
        (late,) = step(client, token, (ep["id"], r["t"], 0))
        assert late["ok"] is False and late["error"] == "ended", late
        final = late["final"]
        assert final["end_reason"] == "release" and final["length"] == 1
        assert final["won"] is None and final["rounds_beaten"] is None
        assert final["verified"] is None and final["seed"] == row_of(engine, ep["id"]).seed

        row = row_of(engine, ep["id"])
        assert row.status == "void" and row.t == 1 and OTHER in (row.engine_error or "")
        assert used(engine, agent) == before - 1
        got = client.get(f"/api/v1/episodes/{ep['id']}", headers=bearer(token)).json()
        assert got["status"] == "void" and got["final"] == final
        again = client.post("/api/v1/episodes", json={"track": "red-1", "keys": [key]},
                            headers=bearer(token)).json()["episodes"]  # fmt: skip
        assert again[0]["status"] == "void" and again[0]["final"] == final
        assert client.get("/api/v1/episodes", headers=bearer(token)).json() == []
        assert client.get(f"/api/episodes/{ep['id']}").status_code == 404
        listed = client.get(f"/api/agents/{agent.slug}/episodes").json()["episodes"]
        assert listed == []


def test_a_resume_forfeit_or_create_finds_the_episode_void_too(app, agents, engine):
    _, token = agents.agent()
    with TestClient(app) as client:
        a, b = create(client, token, n=2)
        for ep in (a, b):
            step(client, token, (ep["id"], 0, 0))
        deploy(app, reordered)
        got = client.get(f"/api/v1/episodes/{a['id']}", headers=bearer(token)).json()
        assert got["status"] == "void" and got["final"]["end_reason"] == "release"
        f = client.post(f"/api/v1/episodes/{b['id']}/forfeit", headers=bearer(token)).json()
        assert f["end_reason"] == "release" and row_of(engine, b["id"]).status == "void"


def test_rows_from_before_digests(app, agents, engine):
    """A row from before digests holds none. Its own release still replays it exactly; another
    can't check it, so it voids it."""
    _, token = agents.agent()
    with TestClient(app) as client:
        mine, theirs = create(client, token, n=2)
        for ep in (mine, theirs):
            step(client, token, (ep["id"], 0, 0))
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE episodes SET last_engine_version = NULL, state_digest = NULL")
            )
            conn.execute(
                text("UPDATE episodes SET engine_version = '0.0.1' WHERE id = :i"),
                {"i": theirs["id"]},
            )
        deploy(app, release=ENGINE_VERSION)
        (ok, gone) = step(client, token, (mine["id"], 1, 0), (theirs["id"], 1, 0))
        assert ok["ok"] and ok["t"] == 2
        assert gone["error"] == "ended" and gone["final"]["end_reason"] == "release"


def test_the_janitor_voids_what_it_cannot_continue_and_keeps_going(app, agents, engine, clock):
    """Idle episodes: one it forfeits, one from another season, one whose release served a step
    it rebuilds differently, and one whose trace doesn't replay (logged, left running)."""
    _, token = agents.agent()
    with TestClient(app) as client:
        idle, old_season, other, broken = create(client, token, n=4)
        for ep in (idle, old_season, other, broken):
            step(client, token, (ep["id"], 0, 0))
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE episodes SET season = '0.0.1' WHERE id = :i"), {"i": old_season["id"]}
            )
            conn.execute(
                text("UPDATE episodes SET last_engine_version = :v, state_digest = 'x' "
                     "WHERE id = :i"),
                {"v": OTHER, "i": other["id"]},
            )  # fmt: skip
            conn.execute(
                text("UPDATE episodes SET trace = :b WHERE id = :i"),
                {"b": struct.pack("<H", 499), "i": broken["id"]},
            )
        clock.advance(minutes=11)
        assert app.state.episodes.janitor(idle_s=600) == {"ended": 1, "voided": 2}
        statuses = {
            k: row_of(engine, ep["id"])
            for k, ep in {"idle": idle, "old": old_season, "other": other, "broken": broken}.items()
        }
        assert statuses["idle"].status == "ended" and statuses["idle"].end_reason == "idle"
        assert statuses["old"].status == "void" and statuses["other"].status == "void"
        assert statuses["broken"].status == "running"


def test_a_void_episode_gives_its_budget_back(make_app, agents, engine):
    add_track(engine, "tiny", budget=1)
    app = make_app()
    _, token = agents.agent()
    with TestClient(app) as client:
        (ep,) = create(client, token, track="tiny")
        step(client, token, (ep["id"], 0, 0))
        spent = client.post("/api/v1/episodes", json={"track": "tiny", "keys": [str(uuid.uuid4())]},
                            headers=bearer(token))  # fmt: skip
        assert spent.status_code == 403
        deploy(app, reordered)
        client.get(f"/api/v1/episodes/{ep['id']}", headers=bearer(token))
        (fresh,) = create(client, token, track="tiny")
        assert fresh["status"] == "running"


def test_another_release_answers_a_retried_last_step_from_the_record(app, agents):
    """Resending the step that ended an episode gets its response replayed, but only from the
    release that played it; another answers from the record."""
    _, token = agents.agent()
    with TestClient(app) as client:
        (ep,) = create(client, token)
        action, last = play(client, token, ep, np.random.default_rng(5))[-1]
        deploy(app)
        (again,) = step(client, token, (ep["id"], last["t"] - 1, action))
        assert again["ok"] is False and again["error"] == "ended"
        assert again["final"] == last["final"]
