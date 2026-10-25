"""House baselines, Lambda task events and migrations."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from arena.db.migrate import _INDEX, migrate, migrations, statements
from arena.engine.spec import ENGINE_VERSION
from arena.house import run_house
from arena.services.seeds import FixedSeeds


def test_house_baselines_play_verified_episodes(app):
    service = app.state.episodes
    random = run_house(service, "random", episodes=12, batch=5)
    assert random["episodes"] == 12 and random["verified"]
    assert random["blinds_beaten"] < 1  # random almost never clears a blind
    smart = run_house(service, "smart", episodes=4, batch=4)
    assert smart["episodes"] == 4 and smart["verified"]
    assert smart["agent"] == "house-smart"


def test_house_agents_appear_in_their_own_section(client):
    run_house(client.app.state.episodes, "random", episodes=3)
    board = client.get("/api/leaderboard").json()
    assert [r["agent"]["slug"] for r in board["house"]] == ["house-random"]
    assert board["ranked"] == [] and board["provisional"] == []


@pytest.mark.slow
def test_smart_baseline_reproduces_the_repo_evaluation(make_app):
    """The runs of jackdaw's examples/evaluate_agents.py, played through the arena: Gym seed s is
    run seed str(s) with sampler seed s. Its smart agent beats 5.404 blinds on average over
    10000000-10000499, the first half of the 1,000 runs in examples/results/eval_results.json."""
    seeds = FixedSeeds((str(s), s) for s in range(10_000_000, 10_000_500))
    s = run_house(make_app(seeds=seeds).state.episodes, "smart", episodes=500, batch=50)
    assert s["blinds_beaten"] == pytest.approx(5.404) and s["length"] == pytest.approx(50.27), s
    assert s["verified"]


def test_events_run_tasks_and_refuse_http_callers(client, make_app, settings):
    assert client.post("/events", json={"task": "warm"}).json() == {"ok": True}
    assert client.post("/events", json={"task": "janitor"}).json() == {"ok": True, "ended": 0}
    # Arrived through a Function URL (the adapter sets the request context): never a task.
    url_context = json.dumps({"http": {"method": "POST", "path": "/events"}})
    for ctx in (url_context, "{}", "not json"):
        r = client.post("/events", json={"task": "janitor"},
                        headers={"x-amzn-request-context": ctx})  # fmt: skip
        assert r.status_code == 403, ctx
    # A direct invocation: the adapter's pass-through context serializes as null.
    r = client.post("/events", json={"task": "janitor"}, headers={"x-amzn-request-context": "null"})
    assert r.json() == {"ok": True, "ended": 0}
    api = make_app(settings=settings.model_copy(update={"role": "api"}))
    from fastapi.testclient import TestClient

    with TestClient(api) as c:
        assert c.post("/events", json={"task": "warm"}).status_code == 200
        health = c.post("/events", json={"task": "health"}).json()
        assert health == {"ok": True, "build": "dev", "engine": ENGINE_VERSION}
        assert c.post("/events", json={"task": "migrate"}).status_code == 403
    assert client.post("/events", json={"task": "nope"}).status_code == 400


def test_migrations_are_idempotent(engine):
    assert migrate(engine) == []  # already applied by the fixture
    with engine.connect() as conn:
        versions = [r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))]
    assert versions == [v for v, _ in migrations()]


def test_migration_statements_split_and_index_rewrite():
    stmts = statements(migrations()[0][1])
    assert all(not s.lstrip().startswith("--") for s in stmts)
    assert sum(s.startswith("CREATE TABLE") for s in stmts) == 8
    index = next(s for s in stmts if s.startswith("CREATE INDEX"))
    rewritten = _INDEX.sub(lambda m: f"CREATE {m.group(1) or ''}INDEX ASYNC ", index, count=1)
    assert rewritten.startswith("CREATE INDEX ASYNC IF NOT EXISTS")
    assert _INDEX.match("CREATE INDEX ASYNC x ON t (c)") is None


def test_audit_replays_the_season_and_catches_a_wrong_record(client, engine):
    from arena.engine.spec import ENGINE_VERSION, SEASON

    run_house(client.app.state.episodes, "random", episodes=6)
    r = client.post("/events", json={"task": "audit"}).json()
    assert r == {"ok": True, "season": SEASON, "engine": ENGINE_VERSION, "checked": 6,
                 "failed": 0, "examples": []}  # fmt: skip
    with engine.begin() as conn:
        eid = conn.execute(text("SELECT id FROM episodes ORDER BY id LIMIT 1")).scalar_one()
        conn.execute(text("UPDATE episodes SET final_state_hash = 'x' WHERE id = :i"), {"i": eid})
    r = client.post("/events", json={"task": "audit"}).json()
    assert r["ok"] is False and r["failed"] == 1
    assert r["examples"] == [f"{eid}: a different final state"]
