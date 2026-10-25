"""Fixtures. The database tests need PostgreSQL 16: ``docker compose up -d db`` (port 54329), or
point ``ARENA_TEST_DATABASE_URL`` elsewhere (CI uses a service container)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from arena.auth.tokens import digest, display_prefix, new_token
from arena.clock import FakeClock
from arena.db import repo
from arena.db.migrate import TABLES, migrate
from arena.main import create_app
from arena.services.seeds import secure_seeds
from arena.settings import Settings

DEFAULT_URL = "postgresql+psycopg://arena:arena@127.0.0.1:54329/arena_test"


def _ensure_database(url: str) -> None:
    u = make_url(url)
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": u.database}
            ).first()
            if not exists:
                conn.exec_driver_sql(f'CREATE DATABASE "{u.database}"')
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def db_url() -> str:
    url = os.environ.get("ARENA_TEST_DATABASE_URL", DEFAULT_URL)
    try:
        _ensure_database(url)
    except Exception as exc:  # noqa: BLE001
        pytest.exit(
            f"PostgreSQL isn't reachable at {url} ({exc}).\n"
            "Start it with `docker compose up -d db` from the repo root, or set "
            "ARENA_TEST_DATABASE_URL.",
            returncode=2,
        )
    return url


@pytest.fixture(scope="session")
def engine(db_url: str) -> Iterator[Engine]:
    eng = create_engine(db_url, pool_size=5, max_overflow=10)
    migrate(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _clean(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    if "engine" not in request.fixturenames:
        return
    eng: Engine = request.getfixturevalue("engine")
    with eng.begin() as conn:
        # DELETE, not TRUNCATE: the same statements work on Aurora DSQL.
        for table in TABLES:
            if table != "tracks":
                conn.exec_driver_sql(f"DELETE FROM {table}")
        conn.exec_driver_sql("DELETE FROM tracks WHERE key <> 'red-1'")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings() -> Settings:
    return Settings(env="test", public_url="http://testserver", cache_size=64)


@pytest.fixture
def make_app(engine: Engine, clock: FakeClock, settings: Settings):
    def build(**kw):
        params = {"settings": settings, "engine": engine, "clock": clock, "seeds": secure_seeds}
        params.update(kw)
        return create_app(**params)

    return build


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


class Agents:
    """Creates users, agents and tokens straight in the database."""

    def __init__(self, engine: Engine, clock: FakeClock) -> None:
        self.engine, self.clock = engine, clock

    def user(self, login: str = "researcher", admin: bool = False) -> repo.User:
        with self.engine.begin() as conn:
            return repo.upsert_identity_user(
                conn, "github", f"id-{login}", login, login.title(), None, admin, self.clock()
            )

    def agent(
        self, slug: str | None = None, user: repo.User | None = None, kind: str = "user",
        unlisted: bool = False,
    ) -> tuple[repo.Agent, str]:  # fmt: skip
        """A new agent and a token for it."""
        user = user or self.user(f"owner-{uuid.uuid4().hex[:6]}")
        slug = slug or f"agent-{uuid.uuid4().hex[:8]}"
        token = new_token()
        with self.engine.begin() as conn:
            aid = repo.create_agent(
                conn, user.id, slug, slug.title(), "", None, kind, unlisted, self.clock()
            )
            repo.create_token(conn, aid, digest(token), display_prefix(token), "", self.clock())
            agent = repo.agent_by_id(conn, aid)
        assert agent is not None
        return agent, token


@pytest.fixture
def agents(engine: Engine, clock: FakeClock) -> Agents:
    return Agents(engine, clock)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sign_in(engine: Engine, clock: FakeClock, settings: Settings):
    """Sign a TestClient in as ``user`` by creating a session directly."""
    import secrets
    from datetime import timedelta

    def go(client: TestClient, user: repo.User) -> TestClient:
        token = secrets.token_urlsafe(32)
        with engine.begin() as conn:
            repo.create_session(conn, digest(token), user.id, clock(), clock() + timedelta(days=1))
        client.cookies.set(settings.session_cookie, token)
        return client

    return go


@pytest.fixture
def ended(engine: Engine, clock: FakeClock):
    """Insert an ended episode with a chosen outcome (for statistics tests)."""
    from arena.engine.spec import SEASON

    def add(agent: repo.Agent, rounds: int, ante: int = 1, won: bool = False,
            reason: str = "lost", track: str = "red-1", t: int = 10,
            verified: bool = True) -> uuid.UUID:  # fmt: skip
        eid = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO episodes (id, agent_id, track, client_key, season, action_version,"
                    " seed, rng_seed, back, stake, max_steps, end_on_win, max_free_moves,"
                    " reward_kind, status, t, trace, created_at, last_step_at, ended_at,"
                    " end_reason, won, ante_reached, rounds_beaten, tape, final_state_hash,"
                    " verified) VALUES (:id, :a, :track, :key, :season, 2, :seed, 1, 'b_red', 1,"
                    " 2000, true, 10, 'sparse', 'ended', :t, :trace, :now, :now, :now, :reason,"
                    " :won, :ante, :rounds, '[]', 'x', :verified)"
                ),
                {"id": eid, "a": agent.id, "track": track, "key": uuid.uuid4(),
                 "season": SEASON, "seed": uuid.uuid4().hex[:16], "t": t,
                 "trace": b"\0\0" * t, "now": clock(), "reason": reason, "won": won,
                 "ante": ante, "rounds": rounds, "verified": verified},
            )  # fmt: skip
        return eid

    return add
