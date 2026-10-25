"""The public API: leaderboard statistics, agent pages, episodes, replays and tapes."""

from __future__ import annotations

import math
import uuid

import numpy as np
import pytest
from sqlalchemy import text

from arena.engine.live import RunSpec, verify_tape
from arena.services.leaderboard import Z95, wilson
from tests.conftest import bearer


def set_budget(engine, k: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE tracks SET episodes_per_agent = :k WHERE key = 'red-1'"), {"k": k}
        )


@pytest.fixture
def budget_3(engine):
    set_budget(engine, 3)
    yield
    set_budget(engine, 500)


def test_wilson_interval():
    lo, hi = wilson(0, 500)
    assert lo == 0.0 and 0.0 < hi < 0.01
    lo, hi = wilson(50, 100)
    assert lo < 0.5 < hi and math.isclose(lo + hi, 1.0)


def test_leaderboard_statistics_and_sections(client, agents, ended, budget_3):
    full, _ = agents.agent("full-run")
    for rounds, won in ((4, False), (6, False), (8, True)):
        ended(full, rounds=rounds, ante=1 + rounds // 3, won=won)
    partial, _ = agents.agent("partial-run")
    ended(partial, rounds=9, ante=4)
    refused, _ = agents.agent("refused-run")
    for reason in ("lost", "lost", "refused"):
        ended(refused, rounds=6, ante=3, reason=reason)
    house, _ = agents.agent("house-random", kind="house")
    ended(house, rounds=0)
    hidden, _ = agents.agent("hidden-run")
    for _ in range(3):
        ended(hidden, rounds=12)
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE agents SET hidden = true WHERE slug = 'hidden-run'"))

    r = client.get("/api/leaderboard")
    assert r.headers["cache-control"] == "public, max-age=0, s-maxage=60"
    board = r.json()
    assert board["k"] == 3
    ranked = {row["agent"]["slug"]: row for row in board["ranked"]}
    assert list(ranked) == ["full-run", "refused-run"]  # by mean blinds: 6.0, then 4.0
    s = ranked["full-run"]["stats"]
    assert s["n"] == 3 and s["blinds_mean"] == 6.0 and ranked["full-run"]["rank"] == 1
    sem = np.std([4, 6, 8], ddof=1) / math.sqrt(3)
    assert math.isclose(s["blinds_sem"], sem)
    assert math.isclose(s["blinds_ci95"][1] - 6.0, Z95 * sem)
    assert math.isclose(s["win_rate"], 1 / 3) and s["win_ci95"] == list(wilson(1, 3))
    # A refused episode (an env bug) scores zero, as in the repo's evaluation.
    assert ranked["refused-run"]["stats"]["blinds_mean"] == 4.0
    assert [row["agent"]["slug"] for row in board["provisional"]] == ["partial-run"]
    assert [row["agent"]["slug"] for row in board["house"]] == ["house-random"]
    assert "hidden-run" not in str(board)


def test_agent_page_and_histogram(client, agents, ended):
    agent, _ = agents.agent("histo")
    for rounds in (0, 2, 2, 5):
        ended(agent, rounds=rounds)
    page = client.get("/api/agents/histo").json()
    assert page["histogram"]["red-1"] == [1, 0, 2, 0, 0, 1]
    assert page["tracks"]["red-1"]["n"] == 4 and len(page["recent"]) == 4
    assert client.get("/api/agents/nope").status_code == 404


def test_episode_pagination(client, agents, ended, clock):
    agent, _ = agents.agent("pager")
    for i in range(5):
        clock.advance(seconds=1)
        ended(agent, rounds=i)
    first = client.get("/api/agents/pager/episodes", params={"limit": 2}).json()
    assert len(first["episodes"]) == 2 and first["next"]
    seen = [e["id"] for e in first["episodes"]]
    cursor = first["next"]
    while cursor:
        page = client.get(
            "/api/agents/pager/episodes", params={"limit": 2, "before": cursor}
        ).json()
        seen += [e["id"] for e in page["episodes"]]
        cursor = page["next"]
    assert len(seen) == len(set(seen)) == 5


def play_to_end(client, token, seed_rng=0):
    r = client.post("/api/v1/episodes", json={"keys": [str(uuid.uuid4())]}, headers=bearer(token))
    ep = r.json()["episodes"][0]
    rng, t, n = np.random.default_rng(seed_rng), 0, ep["n_actions"]
    while True:
        res = client.post("/api/v1/step", json={"steps": [{"id": ep["id"], "t": t,
                          "action": int(rng.integers(n))}]}, headers=bearer(token))  # fmt: skip
        out = res.json()["results"][0]
        if out["final"]:
            return ep["id"], out
        t, n = out["t"], out["n_actions"]


def test_running_episodes_are_public_but_keep_their_secrets(client, agents):
    _, token = agents.agent("live-one")
    r = client.post("/api/v1/episodes", json={"keys": [str(uuid.uuid4())]}, headers=bearer(token))
    eid = r.json()["episodes"][0]["id"]
    pub = client.get(f"/api/episodes/{eid}")
    assert pub.json()["status"] == "running" and pub.json()["final"] is None
    assert pub.headers["cache-control"] == "public, max-age=0, s-maxage=5"
    assert client.get(f"/api/episodes/{eid}/frames").status_code == 404
    assert client.get(f"/api/episodes/{eid}/tape").status_code == 404


def test_replay_frames_and_tape_verify(client, agents):
    _, token = agents.agent("replayer")
    eid, final = play_to_end(client, token, 3)
    summary = client.get(f"/api/episodes/{eid}")
    assert summary.json()["final"]["seed"] == final["final"]["seed"]
    assert "immutable" in summary.headers["cache-control"]

    tape = client.get(f"/api/episodes/{eid}/tape").json()
    spec = RunSpec(back=tape["back"], stake=tape["stake"], seed=tape["seed"],
                   rng_seed=int(tape["rng_seed"]), max_steps=tape["max_steps"])  # fmt: skip
    import json

    lines = [json.dumps(a, separators=(",", ":")) for a in tape["tape"]]
    assert (
        verify_tape(spec, lines) == tape["final_state_hash"] == final["final"]["final_state_hash"]
    )
    assert len(tape["indices"]) == final["t"]

    r = client.get(f"/api/episodes/{eid}/frames")
    assert "immutable" in r.headers["cache-control"]
    doc = r.json()
    assert doc["total"] == final["t"] + 1 == len(doc["frames"])
    first, last = doc["frames"][0], doc["frames"][-1]
    assert first["phase"] == "blind_select"
    assert first["description"].startswith(("Select", "Skip"))
    assert last["action"] is None and last["description"] is None
    part = client.get(f"/api/episodes/{eid}/frames", params={"from": 2, "limit": 3}).json()
    assert [f["i"] for f in part["frames"]] == [2, 3, 4][: max(0, doc["total"] - 2)]


def test_catalog_and_tracks(client):
    cat = client.get("/api/catalog").json()
    assert cat["centers"]["j_joker"]["name"] == "Joker"
    assert cat["blinds"]["bl_hook"]["name"] == "The Hook"
    tracks = client.get("/api/tracks").json()
    assert tracks[0]["key"] == "red-1" and tracks[0]["episodes_per_agent"] == 500


def test_tapes_name_the_release_that_recorded_them(client, engine):
    from arena.engine.spec import ENGINE_VERSION, SEASON, SEASONS, replayable
    from arena.house import run_house

    assert ENGINE_VERSION in SEASONS[SEASON].engines and replayable(SEASON)
    assert not replayable("9.9.9")
    run_house(client.app.state.episodes, "random", episodes=1)
    with engine.connect() as conn:
        eid = conn.execute(text("SELECT id FROM episodes")).scalar_one()
    assert client.get(f"/api/episodes/{eid}/tape").json()["engine_version"] == ENGINE_VERSION
    with engine.begin() as conn:  # a row from before the column: its season's first release
        conn.execute(text("UPDATE episodes SET engine_version = NULL"))
    assert client.get(f"/api/episodes/{eid}/tape").json()["engine_version"] == SEASON
