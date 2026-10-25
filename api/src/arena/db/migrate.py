"""Schema migrations: numbered SQL files, applied once each, in order.

Aurora DSQL runs each DDL statement in its own transaction and never mixes DDL with DML, so the
runner executes statement by statement in autocommit. The statements are idempotent
(``IF NOT EXISTS``, ``ON CONFLICT DO NOTHING``), so a migration interrupted halfway can simply
run again. On DSQL, ``CREATE INDEX`` becomes ``CREATE INDEX ASYNC`` and the runner waits for each
job.
"""

from __future__ import annotations

import re
from importlib.resources import files

from sqlalchemy import Connection, Engine, text

TABLES = ("users", "identities", "sessions", "agents", "api_tokens", "tracks", "quotas", "episodes")


def migrations() -> list[tuple[str, str]]:
    """``(version, sql)`` for every migration file, in order."""
    out = []
    for f in (files("arena.db") / "migrations").iterdir():
        if f.name.endswith(".sql"):
            out.append((f.name.removesuffix(".sql"), f.read_text(encoding="utf-8")))
    return sorted(out)


def statements(sql: str) -> list[str]:
    """The statements of a migration file: ``--`` comments dropped, split at ``;``."""
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


_INDEX = re.compile(r"^CREATE\s+(UNIQUE\s+)?INDEX\s+(?!ASYNC)", re.IGNORECASE)


def migrate(engine: Engine, *, dsql: bool = False) -> list[str]:
    """Apply pending migrations; return the versions applied."""
    applied: list[str] = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.exec_driver_sql("SELECT version FROM schema_migrations")}
        for version, sql in migrations():
            if version in done:
                continue
            for stmt in statements(sql):
                _execute(conn, stmt, dsql)
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:v) ON CONFLICT DO NOTHING"),
                {"v": version},
            )
            applied.append(version)
    return applied


def _execute(conn: Connection, stmt: str, dsql: bool) -> None:
    if dsql and _INDEX.match(stmt):
        stmt = _INDEX.sub(lambda m: f"CREATE {m.group(1) or ''}INDEX ASYNC ", stmt, count=1)
        result = conn.exec_driver_sql(stmt)
        job_id = result.scalar() if result.returns_rows else None
        if job_id:
            conn.exec_driver_sql("CALL sys.wait_for_job(%s)", (job_id,))
        return
    conn.exec_driver_sql(stmt)


def grant_app_role(engine: Engine, user: str, role_arn: str) -> None:
    """On DSQL: let the api Lambda's IAM role connect as a least-privilege database role that
    can read and write the tables but not change the schema. Run as admin; idempotent."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", user):
        raise ValueError(f"bad database role name {user!r}")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :u"), {"u": user})
        if exists.first() is None:
            conn.exec_driver_sql(f"CREATE ROLE {user} WITH LOGIN")
        mapped = conn.execute(
            text("SELECT 1 FROM sys.iam_pg_role_mappings WHERE pg_role_name = :u AND arn = :a"),
            {"u": user, "a": role_arn},
        )
        if mapped.first() is None:
            arn = role_arn.replace("'", "''")
            conn.exec_driver_sql(f"AWS IAM GRANT {user} TO '{arn}'")
        conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {user}")
        for table in TABLES:
            conn.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {user}")
