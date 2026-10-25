"""Against a real Aurora DSQL cluster: the migrations, the least-privilege app role, a whole
episode through the API and its audit, and a step race between two processes.

CI runs these on main against the arena-ci scratch cluster. Locally::

    ARENA_TEST_DSQL_ENDPOINT=<id>.dsql.us-west-2.on.aws uv run --extra aws pytest -m dsql

with AWS credentials that may connect as admin and as ``arena_app``. The app role is mapped to
the caller's IAM role; set ``ARENA_TEST_DSQL_APP_ROLE_ARN`` when that role has a path (SSO roles
do). The tests wipe the cluster's tables: never point them at the production cluster.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from arena.clock import FakeClock
from arena.db.engine import make_engine
from arena.db.migrate import TABLES, grant_app_role, migrate
from arena.engine.spec import ENGINE_VERSION, SEASON
from arena.main import create_app
from arena.services.audit import audit
from arena.settings import Settings
from tests.conftest import Agents, bearer

pytestmark = pytest.mark.dsql

ENDPOINT = os.environ.get("ARENA_TEST_DSQL_ENDPOINT", "")
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"


def _settings(role: str) -> Settings:
    return Settings(
        env="test", public_url="http://testserver", db="dsql", role=role,
        dsql_endpoint=ENDPOINT, aws_region=REGION, cache_size=64,
    )  # fmt: skip


def _caller_role_arn() -> str:
    if arn := os.environ.get("ARENA_TEST_DSQL_APP_ROLE_ARN"):
        return arn
    import boto3

    caller = boto3.client("sts", region_name=REGION).get_caller_identity()["Arn"]
    m = re.fullmatch(r"arn:aws:sts::(\d{12}):assumed-role/([^/]+)/.+", caller)
    if m is None:
        pytest.skip(f"can't tell the IAM role of {caller}; set ARENA_TEST_DSQL_APP_ROLE_ARN")
    return f"arn:aws:iam::{m[1]}:role/{m[2]}"


def _wipe(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in TABLES:
            if table != "tracks":
                conn.exec_driver_sql(f"DELETE FROM {table}")


@pytest.fixture(scope="module")
def admin() -> Iterator[Engine]:
    if not ENDPOINT:
        pytest.skip("ARENA_TEST_DSQL_ENDPOINT isn't set")
    engine = make_engine(_settings("tasks"))  # tasks connect as admin
    migrate(engine, dsql=True)
    _wipe(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(admin: Engine) -> Iterator[Engine]:
    """Connected as the least-privilege role the api function uses."""
    grant_app_role(admin, "arena_app", _caller_role_arn())
    engine = make_engine(_settings("api"))
    yield engine
    engine.dispose()


def test_migrations_are_idempotent_and_build_every_index(admin):
    assert migrate(admin, dsql=True) == []
    with admin.connect() as conn:
        names = {r[0] for r in conn.execute(text("SELECT indexname FROM pg_indexes"))}
    assert {"episodes_agent_status", "episodes_board", "episodes_idle"} <= names


def test_the_app_role_cannot_change_the_schema(app_engine):
    denied = pytest.raises(Exception, match="(?i)permission|denied|not authorized")
    with denied, app_engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE intruder (id int PRIMARY KEY)")


def test_an_episode_from_start_to_replay(app_engine):
    clock = FakeClock()
    agent, token = Agents(app_engine, clock).agent()
    with TestClient(create_app(_settings("api"), engine=app_engine, clock=clock)) as c:
        r = c.post("/api/v1/episodes", json={"track": "red-1", "keys": ["5a1d0e9e-0000-4000-8000-000000000001"]},
                   headers=bearer(token))  # fmt: skip
        assert r.status_code == 201, r.text
        (ep,) = r.json()["episodes"]
        rng, t, n = np.random.default_rng(0), 0, ep["n_actions"]
        while True:
            r = c.post("/api/v1/step", json={"steps": [{"id": ep["id"], "t": t, "action": int(rng.integers(n))}]},
                       headers=bearer(token))  # fmt: skip
            (res,) = r.json()["results"]
            assert res["ok"], res
            if res["final"]:
                break
            t, n = res["t"], res["n_actions"]
        assert res["final"]["verified"] is True
        board = c.get("/api/leaderboard").json()
        assert [row["agent"]["slug"] for row in board["provisional"]] == [agent.slug]
        frames = c.get(f"/api/episodes/{ep['id']}/frames").json()
        assert frames["total"] == res["final"]["length"] + 1
        tape = c.get(f"/api/episodes/{ep['id']}/tape").json()
        assert tape["engine_version"] == ENGINE_VERSION
    result = audit(app_engine, SEASON)
    assert result["ok"] and result["checked"] == 1, result


def test_two_processes_racing_on_one_step(app_engine):
    """Different actions for the same t from two API processes: exactly one wins, and the
    episode stays consistent (DSQL's optimistic concurrency, or the t check, rejects the
    other)."""
    clock = FakeClock()
    _, token = Agents(app_engine, clock).agent()
    apps = [create_app(_settings("api"), engine=app_engine, clock=clock) for _ in range(2)]
    with TestClient(apps[0]) as a, TestClient(apps[1]) as b:
        r = a.post("/api/v1/episodes", json={"track": "red-1", "keys": ["5a1d0e9e-0000-4000-8000-000000000002"]},
                   headers=bearer(token))  # fmt: skip
        (ep,) = r.json()["episodes"]
        if ep["n_actions"] < 2:
            pytest.skip("only one legal first action on this seed")
        b.get(f"/api/v1/episodes/{ep['id']}", headers=bearer(token))  # both processes cache it
        out: dict[int, dict] = {}

        def go(i: int, client: TestClient) -> None:
            r = client.post("/api/v1/step", json={"steps": [{"id": ep["id"], "t": 0, "action": i}]},
                            headers=bearer(token))  # fmt: skip
            out[i] = r.json()["results"][0]

        threads = [threading.Thread(target=go, args=(i, c)) for i, c in enumerate((a, b))]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert sorted(r["ok"] for r in out.values()) == [False, True], out
        loser = next(r for r in out.values() if not r["ok"])
        assert loser["error"] == "conflict"
        state = a.get(f"/api/v1/episodes/{ep['id']}", headers=bearer(token)).json()
        assert state["t"] == 1
