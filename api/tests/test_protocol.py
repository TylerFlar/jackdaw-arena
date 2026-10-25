"""The agent protocol over HTTP, against PostgreSQL."""

from __future__ import annotations

import base64
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient
from jackdaw.env import BalatroGymnasiumEnv, DirectAdapter
from jackdaw.env.rewards import ShapedReward, sparse_reward
from pydantic import SecretStr
from sqlalchemy import text

from arena.services.seeds import FixedSeeds
from tests.conftest import bearer


def add_track(engine, key: str, max_steps: int = 2000, budget: int = 500) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tracks (key, name, back, stake, max_steps, end_on_win, "
                "max_free_moves, episodes_per_agent) VALUES (:k, :k, 'b_red', 1, :m, true, 10, :b)"
            ),
            {"k": key, "m": max_steps, "b": budget},
        )


def create(client: TestClient, token: str, n: int = 1, track: str = "red-1", **body) -> list[dict]:
    keys = [str(uuid.uuid4()) for _ in range(n)]
    r = client.post(
        "/api/v1/episodes", json={"track": track, "keys": keys, **body}, headers=bearer(token)
    )
    assert r.status_code == 201, r.text
    return r.json()["episodes"]


def step(client: TestClient, token: str, *items: tuple[str, int, int]) -> list[dict]:
    r = client.post(
        "/api/v1/step",
        json={"steps": [{"id": i, "t": t, "action": a} for i, t, a in items]},
        headers=bearer(token),
    )
    assert r.status_code == 200, r.text
    return r.json()["results"]


def flat(obs: dict[str, np.ndarray]) -> bytes:
    return np.concatenate([obs[k].ravel() for k in obs]).tobytes()


def play(client, token, ep, rng, limit=10_000) -> list[tuple[int, dict]]:
    """Play one episode with random legal actions; return every (action, result)."""
    out, t, n = [], ep["t"], ep["n_actions"]
    while len(out) < limit:
        a = int(rng.integers(n))
        (r,) = step(client, token, (ep["id"], t, a))
        assert r["ok"], r
        out.append((a, r))
        if r["final"] is not None:
            return out
        t, n = r["t"], r["n_actions"]
    return out


# --- fidelity ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("kind", "fn"), [("sparse", sparse_reward), ("shaped", ShapedReward())])
@pytest.mark.parametrize("max_steps", [2000, 25])
def test_remote_episode_equals_local_gymnasium_env(make_app, agents, engine, kind, fn, max_steps):
    """Over HTTP, seed str(N) with sampler seed N is BalatroGymnasiumEnv.reset(seed=N): same obs
    bytes, mask, rewards, flags and end-of-episode info at every step."""
    seeds = [11, 2026, 31337]
    track = "red-1" if max_steps == 2000 else "short"
    if track == "short":
        add_track(engine, "short", max_steps=max_steps)
    app = make_app(seeds=FixedSeeds((str(n), n) for n in seeds))
    _, token = agents.agent()
    with TestClient(app) as client:
        for n in seeds:
            (ep,) = create(client, token, track=track, reward={"kind": kind})
            local = BalatroGymnasiumEnv(
                adapter_factory=DirectAdapter, reward_fn=fn, max_steps=max_steps
            )
            obs, _ = local.reset(seed=n)
            assert base64.b64decode(ep["obs"]) == flat(obs)
            rng = np.random.default_rng(n)
            t, n_actions, info = 0, ep["n_actions"], {}
            while True:
                assert local.action_masks().sum() == n_actions
                a = int(rng.integers(n_actions))
                obs, reward, term, trunc, info = local.step(a)
                (r,) = step(client, token, (ep["id"], t, a))
                assert base64.b64decode(r["obs"]) == flat(obs)
                assert (r["reward"], r["terminated"], r["truncated"]) == (reward, term, trunc)
                t, n_actions = r["t"], r["n_actions"]
                if term or trunc:
                    break
            final = r["final"]
            assert final["verified"] is True and final["seed"] == str(n)
            assert final["ante_reached"] == info["balatro/ante_reached"]
            assert final["rounds_beaten"] == info["balatro/rounds_beaten"]
            assert final["won"] == info["balatro/won"]


def test_no_cache_and_two_processes_agree_with_one(make_app, agents, settings, engine):
    """Every request rebuilt from the database (cache off), or steps alternating between two
    processes, gives exactly the responses of one process with a warm cache."""
    seeds = [(f"SAMESEEDFORALL{i:02d}", 77 + i) for i in range(3)]
    _, token = agents.agent()

    def run(clients) -> list[list[dict]]:
        runs = []
        for k in range(3):
            (ep,) = create(clients[0], token)
            rng, t, n, results = np.random.default_rng(k), 0, ep["n_actions"], []
            while True:
                c = clients[len(results) % len(clients)]
                (r,) = step(c, token, (ep["id"], t, int(rng.integers(n))))
                assert r["ok"], r
                results.append({**r, "id": None})
                if r["final"]:
                    break
                t, n = r["t"], r["n_actions"]
            runs.append(results)
        with engine.begin() as conn:  # the next pass reuses the seeds
            conn.exec_driver_sql("DELETE FROM episodes")
            conn.exec_driver_sql("DELETE FROM quotas")
        return runs

    warm = make_app(seeds=FixedSeeds(seeds))
    cold = make_app(seeds=FixedSeeds(seeds), settings=settings.model_copy(update={"cache_size": 0}))
    a, b = make_app(seeds=FixedSeeds(seeds)), make_app(seeds=FixedSeeds([]))
    with TestClient(warm) as w:
        expected = run([w])
    with TestClient(cold) as c:
        assert run([c]) == expected
    with TestClient(a) as ca, TestClient(b) as cb:
        assert run([ca, cb]) == expected


# --- protocol semantics ------------------------------------------------------------------------


def test_retry_returns_the_same_response_and_conflict_reports_t(client, agents):
    _, token = agents.agent()
    (ep,) = create(client, token)
    (first,) = step(client, token, (ep["id"], 0, 0))
    (again,) = step(client, token, (ep["id"], 0, 0))
    assert first == again  # a lost response is recovered by resending
    (other,) = step(client, token, (ep["id"], 0, 1 if ep["n_actions"] > 1 else 0))
    if ep["n_actions"] > 1:
        assert other == {**other, "ok": False, "error": "conflict", "t": 1}
    (stale,) = step(client, token, (ep["id"], 5, 0))
    assert stale["ok"] is False and stale["error"] == "conflict" and stale["t"] == 1


def test_illegal_action_changes_nothing(client, agents):
    _, token = agents.agent()
    (ep,) = create(client, token)
    (bad,) = step(client, token, (ep["id"], 0, ep["n_actions"]))
    assert bad["ok"] is False and bad["error"] == "illegal_action" and bad["t"] == 0
    resumed = client.get(f"/api/v1/episodes/{ep['id']}", headers=bearer(token)).json()
    assert resumed["t"] == 0 and resumed["obs"] == ep["obs"]


def test_batch_mixes_results_and_rejects_duplicates(client, agents):
    _, token = agents.agent()
    a, b = create(client, token, n=2)
    results = step(client, token, (a["id"], 0, 0), (b["id"], 3, 0), (str(uuid.uuid4()), 0, 0))
    assert [r["ok"] for r in results] == [True, False, False]
    assert [r["error"] for r in results] == [None, "conflict", "not_found"]
    dup = client.post(
        "/api/v1/step",
        json={"steps": [{"id": a["id"], "t": 1, "action": 0}] * 2},
        headers=bearer(token),
    )
    assert dup.status_code == 422


def test_agents_cannot_touch_each_others_episodes(client, agents):
    _, mine = agents.agent()
    _, theirs = agents.agent()
    (ep,) = create(client, mine)
    (r,) = step(client, theirs, (ep["id"], 0, 0))
    assert r["error"] == "not_found"
    assert client.get(f"/api/v1/episodes/{ep['id']}", headers=bearer(theirs)).status_code == 404
    assert (
        client.post(f"/api/v1/episodes/{ep['id']}/forfeit", headers=bearer(theirs)).status_code
        == 404
    )


def test_creation_is_idempotent_by_key(client, agents):
    _, token = agents.agent()
    keys = [str(uuid.uuid4()) for _ in range(3)]
    first = client.post("/api/v1/episodes", json={"keys": keys}, headers=bearer(token)).json()
    again = client.post("/api/v1/episodes", json={"keys": keys}, headers=bearer(token)).json()
    assert [e["id"] for e in first["episodes"]] == [e["id"] for e in again["episodes"]]
    me = client.get("/api/v1/me", headers=bearer(token)).json()
    assert me["used"] == {"red-1": 3} and me["running"] == 3


def test_budget_and_running_cap(make_app, agents, engine, settings):
    add_track(engine, "tiny", budget=3)
    app = make_app(settings=settings.model_copy(update={"max_running_per_agent": 2}))
    _, token = agents.agent()
    with TestClient(app) as client:
        a, b = create(client, token, n=2, track="tiny")
        over = client.post("/api/v1/episodes", json={"track": "tiny", "keys": [str(uuid.uuid4())]},
                           headers=bearer(token))  # fmt: skip
        assert over.status_code == 429 and over.json()["error"] == "too_many_running"
        client.post(f"/api/v1/episodes/{a['id']}/forfeit", headers=bearer(token))
        create(client, token, track="tiny")  # the third and last
        client.post(f"/api/v1/episodes/{b['id']}/forfeit", headers=bearer(token))
        done = client.post("/api/v1/episodes", json={"track": "tiny", "keys": [str(uuid.uuid4())]},
                           headers=bearer(token))  # fmt: skip
        assert done.status_code == 403 and done.json()["error"] == "budget_exhausted"


def test_unknown_track_and_bad_reward(client, agents):
    _, token = agents.agent()
    r = client.post("/api/v1/episodes", json={"track": "nope", "keys": [str(uuid.uuid4())]},
                    headers=bearer(token))  # fmt: skip
    assert r.status_code == 404
    r = client.post(
        "/api/v1/episodes",
        json={"keys": [str(uuid.uuid4())], "reward": {"kind": "sparse", "weights": {"win": 1}}},
        headers=bearer(token),
    )
    assert r.status_code == 422 and r.json()["error"] == "bad_reward"


# --- secrecy, endings --------------------------------------------------------------------------


def test_seed_stays_hidden_until_the_end(client, agents, engine):
    _, token = agents.agent()
    (ep,) = create(client, token)
    with engine.connect() as conn:
        seed = conn.execute(
            text("SELECT seed FROM episodes WHERE id = :i"), {"i": ep["id"]}
        ).scalar()
    seen = [create(client, token)[0]]
    rng, t, n = np.random.default_rng(0), 0, ep["n_actions"]
    while True:
        r = client.post("/api/v1/step", json={"steps": [{"id": ep["id"], "t": t,
                        "action": int(rng.integers(n))}]}, headers=bearer(token))  # fmt: skip
        body = r.json()["results"][0]
        if body["final"]:
            assert body["final"]["seed"] == seed
            break
        assert seed not in r.text
        seen.append(client.get(f"/api/v1/episodes/{ep['id']}", headers=bearer(token)).json())
        assert seed not in str(seen[-1])
        t, n = body["t"], body["n_actions"]
    assert seed not in client.get("/api/v1/episodes", headers=bearer(token)).text


def test_final_step_retry_from_a_fresh_process(make_app, agents):
    """The response to the step that ended an episode can be recovered by resending it, even
    from a process that never saw the episode: the database replays it."""
    _, token = agents.agent()
    with TestClient(make_app()) as one:
        (ep,) = create(one, token)
        action, last = play(one, token, ep, np.random.default_rng(9))[-1]
    with TestClient(make_app()) as two:
        resumed = two.get(f"/api/v1/episodes/{ep['id']}", headers=bearer(token)).json()
        assert resumed["status"] == "ended" and resumed["final"] == last["final"]
        (again,) = step(two, token, (ep["id"], last["t"] - 1, action))
        assert again == last
        (other,) = step(two, token, (ep["id"], last["t"], 0))
        assert other["ok"] is False and other["error"] == "ended"


def test_forfeit_is_scored_and_idempotent(client, agents):
    _, token = agents.agent()
    (ep,) = create(client, token)
    (r,) = step(client, token, (ep["id"], 0, 0))
    f1 = client.post(f"/api/v1/episodes/{ep['id']}/forfeit", headers=bearer(token)).json()
    f2 = client.post(f"/api/v1/episodes/{ep['id']}/forfeit", headers=bearer(token)).json()
    assert f1 == f2 and f1["end_reason"] == "forfeit" and f1["verified"] and f1["length"] == 1
    assert f1["ante_reached"] == 1 and isinstance(f1["rng_seed"], str)
    (late,) = step(client, token, (ep["id"], 1, 0))
    assert (
        late["ok"] is False
        and late["error"] == "ended"
        and late["final"]["end_reason"] == "forfeit"
    )


def test_janitor_ends_idle_episodes(app, agents, clock):
    _, token = agents.agent()
    with TestClient(app) as client:
        idle, busy = create(client, token, n=2)
        clock.advance(minutes=5)
        step(client, token, (busy["id"], 0, 0))
        clock.advance(minutes=6)
        assert app.state.episodes.janitor(idle_s=600) == 1
        r = client.get(f"/api/v1/episodes/{idle['id']}", headers=bearer(token)).json()
        assert r["status"] == "ended" and r["final"]["end_reason"] == "idle"
        assert (
            client.get(f"/api/v1/episodes/{busy['id']}", headers=bearer(token)).json()["status"]
            == "running"
        )


# --- auth --------------------------------------------------------------------------------------


def test_tokens_are_required_and_revocable(client, agents, engine, clock):
    agent, token = agents.agent()
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers=bearer("jdk_wrong")).status_code == 401
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200
    from arena.db import repo

    with engine.begin() as conn:
        (tok,) = repo.tokens_of(conn, agent.id)
        assert repo.revoke_token(conn, tok["id"], [agent.id], clock())
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 401


def test_origin_verify_secret(make_app, agents, settings):
    app = make_app(
        settings=settings.model_copy(update={"origin_verify_secret": SecretStr("s3cret")})
    )
    _, token = agents.agent()
    with TestClient(app) as client:
        assert client.get("/api/v1/me", headers=bearer(token)).status_code == 403
        ok = client.get("/api/v1/me", headers={**bearer(token), "X-Origin-Verify": "s3cret"})
        assert ok.status_code == 200
        assert ok.headers["cache-control"] == "no-store"


def test_spec_describes_the_local_env(client):
    spec = client.get("/api/v1/spec").json()
    local = BalatroGymnasiumEnv(adapter_factory=DirectAdapter)
    assert spec["max_actions"] == local.action_space.n
    assert spec["action_version"] == local.action_version
    for f in spec["obs"]["fields"]:
        assert tuple(f["shape"]) == local.observation_space[f["name"]].shape
    assert spec["tracks"][0]["key"] == "red-1"
