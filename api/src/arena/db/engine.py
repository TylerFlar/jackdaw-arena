"""Database engines: plain PostgreSQL, or Aurora DSQL with IAM authentication."""

from __future__ import annotations

from collections.abc import Callable

import psycopg
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import DBAPIError

from arena.settings import Settings


def make_engine(settings: Settings) -> Engine:
    if settings.db == "dsql":
        import certifi
        from aurora_dsql_sqlalchemy import create_dsql_engine

        if not settings.dsql_endpoint:
            raise ValueError("ARENA_DSQL_ENDPOINT is required with ARENA_DB=dsql")
        # One request at a time per Lambda environment: a pool of one, recycled before DSQL's
        # one-hour connection limit.
        return create_dsql_engine(
            host=settings.dsql_endpoint,
            user="admin" if settings.role == "tasks" else settings.dsql_user,
            driver="psycopg",
            # The connector's default ("system") is wherever psycopg-binary's bundled OpenSSL
            # looks, which isn't the OS store on Windows, nor necessarily on Debian. certifi's
            # Mozilla bundle includes the Amazon roots DSQL's certificates chain to.
            sslrootcert=certifi.where(),
            application_name="jackdaw-arena",
            pool_size=1,
            max_overflow=2,
            pool_recycle=3000,
            pool_pre_ping=True,
            connect_args={"region": settings.aws_region},
        )
    return create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=10)


def is_serialization_failure(exc: BaseException) -> bool:
    """A transaction lost an optimistic-concurrency race (DSQL OC000/OC001, SQLSTATE 40001)."""
    orig = exc.orig if isinstance(exc, DBAPIError) else exc
    return isinstance(orig, psycopg.errors.SerializationFailure) or (
        isinstance(orig, psycopg.Error) and getattr(orig, "sqlstate", None) == "40001"
    )


def retrying[T](fn: Callable[[], T], attempts: int = 3) -> T:
    """Run ``fn`` (one transaction), retrying when it loses a concurrency race."""
    for attempt in range(attempts):
        try:
            return fn()
        except DBAPIError as exc:
            if attempt == attempts - 1 or not is_serialization_failure(exc):
                raise
    raise AssertionError("unreachable")
