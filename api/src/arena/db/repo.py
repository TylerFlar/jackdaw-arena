"""All SQL. Functions take a ``Connection`` so callers decide what one transaction covers.

The SQL is plain PostgreSQL that Aurora DSQL also accepts: arrays appear only at query time
(``unnest``, ``ANY``), and the per-step trace is ``bytea`` appended with ``||``.
"""

from __future__ import annotations

import json
import struct
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from arena.engine.live import Outcome, RunSpec

# --- traces ------------------------------------------------------------------------------------


def pack_index(a: int) -> bytes:
    return struct.pack("<H", a)


def unpack_trace(trace: bytes) -> list[int]:
    return [a for (a,) in struct.iter_unpack("<H", trace)]


# --- tracks ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Track:
    key: str
    name: str
    back: str
    stake: int
    max_steps: int
    end_on_win: bool
    max_free_moves: int | None
    episodes_per_agent: int
    active: bool

    def public(self) -> dict[str, Any]:
        return {
            "key": self.key, "name": self.name, "back": self.back, "stake": self.stake,
            "max_steps": self.max_steps, "end_on_win": self.end_on_win,
            "max_free_moves": self.max_free_moves, "episodes_per_agent": self.episodes_per_agent,
        }  # fmt: skip


_TRACK_COLS = (
    "key, name, back, stake, max_steps, end_on_win, max_free_moves, episodes_per_agent, active"
)


def list_tracks(conn: Connection) -> list[Track]:
    rows = conn.execute(text(f"SELECT {_TRACK_COLS} FROM tracks WHERE active ORDER BY key"))
    return [Track(*r) for r in rows]


def get_track(conn: Connection, key: str) -> Track | None:
    row = conn.execute(text(f"SELECT {_TRACK_COLS} FROM tracks WHERE key = :k"), {"k": key}).first()
    return Track(*row) if row else None


# --- users, identities, sessions ---------------------------------------------------------------


@dataclass(frozen=True)
class User:
    id: uuid.UUID
    login: str
    name: str | None
    avatar_url: str | None
    is_admin: bool


_USER_COLS = "u.id, u.login, u.name, u.avatar_url, u.is_admin"


def upsert_identity_user(
    conn: Connection,
    provider: str,
    subject: str,
    login: str,
    name: str | None,
    avatar_url: str | None,
    is_admin: bool,
    now: datetime,
) -> User:
    """The user behind an external identity, created on first sign-in. Profile fields follow
    the provider; accounts are never linked by email."""
    row = conn.execute(
        text(
            f"SELECT {_USER_COLS} FROM identities i JOIN users u ON u.id = i.user_id "
            "WHERE i.provider = :p AND i.subject = :s"
        ),
        {"p": provider, "s": subject},
    ).first()
    if row:
        conn.execute(
            text(
                "UPDATE users SET login = :login, name = :name, avatar_url = :avatar, "
                "is_admin = :admin WHERE id = :id"
            ),
            {"login": login, "name": name, "avatar": avatar_url, "admin": is_admin, "id": row[0]},
        )
        return User(row[0], login, name, avatar_url, is_admin)
    uid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO users (id, login, name, avatar_url, is_admin, created_at) "
            "VALUES (:id, :login, :name, :avatar, :admin, :now)"
        ),
        {"id": uid, "login": login, "name": name, "avatar": avatar_url, "admin": is_admin,
         "now": now},
    )  # fmt: skip
    conn.execute(
        text(
            "INSERT INTO identities (provider, subject, user_id, created_at) "
            "VALUES (:p, :s, :u, :now)"
        ),
        {"p": provider, "s": subject, "u": uid, "now": now},
    )
    return User(uid, login, name, avatar_url, is_admin)


def create_session(
    conn: Connection, id_hash: str, user_id: uuid.UUID, now: datetime, expires: datetime
) -> None:
    conn.execute(
        text(
            "INSERT INTO sessions (id_hash, user_id, created_at, expires_at) "
            "VALUES (:h, :u, :now, :exp)"
        ),
        {"h": id_hash, "u": user_id, "now": now, "exp": expires},
    )


def session_user(conn: Connection, id_hash: str, now: datetime) -> User | None:
    row = conn.execute(
        text(
            f"SELECT {_USER_COLS} FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.id_hash = :h AND s.expires_at > :now"
        ),
        {"h": id_hash, "now": now},
    ).first()
    return User(*row) if row else None


def delete_session(conn: Connection, id_hash: str) -> None:
    conn.execute(text("DELETE FROM sessions WHERE id_hash = :h"), {"h": id_hash})


# --- agents and tokens -------------------------------------------------------------------------


@dataclass(frozen=True)
class Agent:
    id: uuid.UUID
    user_id: uuid.UUID
    slug: str
    name: str
    description: str
    url: str | None
    kind: str
    unlisted: bool
    hidden: bool
    created_at: datetime
    owner_login: str | None = None
    owner_avatar: str | None = None


_AGENT_COLS = (
    "a.id, a.user_id, a.slug, a.name, a.description, a.url, a.kind, a.unlisted, a.hidden, "
    "a.created_at, u.login, u.avatar_url"
)
_AGENT_FROM = "agents a LEFT JOIN users u ON u.id = a.user_id"


def agent_by_slug(conn: Connection, slug: str) -> Agent | None:
    row = conn.execute(
        text(f"SELECT {_AGENT_COLS} FROM {_AGENT_FROM} WHERE a.slug = :s"), {"s": slug}
    ).first()
    return Agent(*row) if row else None


def agent_by_id(conn: Connection, agent_id: uuid.UUID) -> Agent | None:
    row = conn.execute(
        text(f"SELECT {_AGENT_COLS} FROM {_AGENT_FROM} WHERE a.id = :i"), {"i": agent_id}
    ).first()
    return Agent(*row) if row else None


def agents_of(conn: Connection, user_id: uuid.UUID) -> list[Agent]:
    rows = conn.execute(
        text(f"SELECT {_AGENT_COLS} FROM {_AGENT_FROM} WHERE a.user_id = :u ORDER BY a.created_at"),
        {"u": user_id},
    )
    return [Agent(*r) for r in rows]


def create_agent(
    conn: Connection,
    user_id: uuid.UUID,
    slug: str,
    name: str,
    description: str,
    url: str | None,
    kind: str,
    unlisted: bool,
    now: datetime,
) -> uuid.UUID:
    aid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO agents (id, user_id, slug, name, description, url, kind, unlisted, "
            "hidden, created_at) VALUES (:id, :u, :slug, :name, :d, :url, :kind, :unl, false, :now)"
        ),
        {"id": aid, "u": user_id, "slug": slug, "name": name, "d": description, "url": url,
         "kind": kind, "unl": unlisted, "now": now},
    )  # fmt: skip
    return aid


def update_agent(conn: Connection, agent_id: uuid.UUID, **fields: Any) -> None:
    allowed = {"name", "description", "url", "unlisted", "hidden"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    assignments = ", ".join(f"{k} = :{k}" for k in sets)
    conn.execute(text(f"UPDATE agents SET {assignments} WHERE id = :id"), {**sets, "id": agent_id})


@dataclass(frozen=True)
class TokenAgent:
    token_id: uuid.UUID
    last_used_at: datetime | None
    agent: Agent


def agent_for_token(conn: Connection, token_hash: str) -> TokenAgent | None:
    row = conn.execute(
        text(
            f"SELECT t.id, t.last_used_at, {_AGENT_COLS} FROM api_tokens t "
            f"JOIN {_AGENT_FROM} ON a.id = t.agent_id "
            "WHERE t.token_hash = :h AND t.revoked_at IS NULL AND NOT a.hidden"
        ),
        {"h": token_hash},
    ).first()
    return TokenAgent(row[0], row[1], Agent(*row[2:])) if row else None


def touch_token(conn: Connection, token_id: uuid.UUID, now: datetime) -> None:
    conn.execute(
        text("UPDATE api_tokens SET last_used_at = :now WHERE id = :id"),
        {"now": now, "id": token_id},
    )


def create_token(
    conn: Connection, agent_id: uuid.UUID, token_hash: str, prefix: str, label: str, now: datetime
) -> uuid.UUID:
    tid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO api_tokens (id, agent_id, token_hash, prefix, label, created_at) "
            "VALUES (:id, :a, :h, :p, :l, :now)"
        ),
        {"id": tid, "a": agent_id, "h": token_hash, "p": prefix, "l": label, "now": now},
    )
    return tid


def tokens_of(conn: Connection, agent_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, prefix, label, created_at, last_used_at FROM api_tokens "
            "WHERE agent_id = :a AND revoked_at IS NULL ORDER BY created_at"
        ),
        {"a": agent_id},
    )
    return [dict(r._mapping) for r in rows]


def revoke_token(
    conn: Connection, token_id: uuid.UUID, agent_ids: Sequence[uuid.UUID], now: datetime
) -> bool:
    result = conn.execute(
        text(
            "UPDATE api_tokens SET revoked_at = :now WHERE id = :id AND revoked_at IS NULL "
            "AND agent_id = ANY(CAST(:agents AS uuid[]))"
        ),
        {"now": now, "id": token_id, "agents": list(agent_ids)},
    )
    return result.rowcount > 0


# --- episodes ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeRow:
    id: uuid.UUID
    agent_id: uuid.UUID
    track: str
    client_key: uuid.UUID
    season: str
    action_version: int
    seed: str
    rng_seed: int
    back: str
    stake: int
    max_steps: int
    end_on_win: bool
    max_free_moves: int | None
    reward_kind: str
    reward_weights: list[float] | None
    status: str
    t: int
    trace: bytes
    created_at: datetime
    last_step_at: datetime
    ended_at: datetime | None
    end_reason: str | None
    won: bool | None
    ante_reached: int | None
    rounds_beaten: int | None
    refused: str | None
    not_ported: str | None
    attempted: Any
    tape: list[Any] | None
    final_state_hash: str | None
    verified: bool | None
    engine_error: str | None
    engine_version: str | None  # the jackdaw release that recorded it (null: the season's first)

    @property
    def spec(self) -> RunSpec:
        return RunSpec(
            back=self.back, stake=self.stake, seed=self.seed, rng_seed=self.rng_seed,
            max_steps=self.max_steps, end_on_win=self.end_on_win,
            max_free_moves=self.max_free_moves, reward_kind=self.reward_kind,
            reward_weights=tuple(self.reward_weights) if self.reward_weights else None,
        )  # fmt: skip

    @property
    def indices(self) -> list[int]:
        return unpack_trace(bytes(self.trace))


_EP_COLS = (
    "id, agent_id, track, client_key, season, action_version, seed, rng_seed, back, stake, "
    "max_steps, end_on_win, max_free_moves, reward_kind, reward_weights, status, t, trace, "
    "created_at, last_step_at, ended_at, end_reason, won, ante_reached, rounds_beaten, refused, "
    "not_ported, attempted, tape, final_state_hash, verified, engine_error, engine_version"
)


def _episode(row: Any) -> EpisodeRow:
    return EpisodeRow(*row)


def episodes_by_keys(
    conn: Connection, agent_id: uuid.UUID, keys: Sequence[uuid.UUID]
) -> list[EpisodeRow]:
    rows = conn.execute(
        text(
            f"SELECT {_EP_COLS} FROM episodes "
            "WHERE agent_id = :a AND client_key = ANY(CAST(:keys AS uuid[]))"
        ),
        {"a": agent_id, "keys": list(keys)},
    )
    return [_episode(r) for r in rows]


def episodes_by_ids(
    conn: Connection, ids: Sequence[uuid.UUID], agent_id: uuid.UUID | None = None
) -> list[EpisodeRow]:
    sql = f"SELECT {_EP_COLS} FROM episodes WHERE id = ANY(CAST(:ids AS uuid[]))"
    params: dict[str, Any] = {"ids": list(ids)}
    if agent_id is not None:
        sql += " AND agent_id = :a"
        params["a"] = agent_id
    return [_episode(r) for r in conn.execute(text(sql), params)]


def count_running(conn: Connection, agent_id: uuid.UUID) -> int:
    return conn.execute(
        text("SELECT count(*) FROM episodes WHERE agent_id = :a AND status = 'running'"),
        {"a": agent_id},
    ).scalar_one()


def reserve_quota(
    conn: Connection, agent_id: uuid.UUID, track: str, season: str, n: int, budget: int
) -> int | None:
    """Count ``n`` more episodes against the agent's budget; the new total, or None if over.
    Two concurrent reservations conflict on the quota row, so the budget is exact."""
    conn.execute(
        text(
            "INSERT INTO quotas (agent_id, track, season, used) VALUES (:a, :t, :s, 0) "
            "ON CONFLICT (agent_id, track, season) DO NOTHING"
        ),
        {"a": agent_id, "t": track, "s": season},
    )
    return conn.execute(
        text(
            "UPDATE quotas SET used = used + :n WHERE agent_id = :a AND track = :t "
            "AND season = :s AND used + :n <= :budget RETURNING used"
        ),
        {"n": n, "a": agent_id, "t": track, "s": season, "budget": budget},
    ).scalar()


def quota_used(conn: Connection, agent_id: uuid.UUID) -> dict[tuple[str, str], int]:
    rows = conn.execute(
        text("SELECT track, season, used FROM quotas WHERE agent_id = :a"), {"a": agent_id}
    )
    return {(t, s): u for t, s, u in rows}


def insert_episodes(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    conn.execute(
        text(
            "INSERT INTO episodes (id, agent_id, track, client_key, season, engine_version, "
            "action_version, seed, rng_seed, back, stake, max_steps, end_on_win, max_free_moves, "
            "reward_kind, reward_weights, status, t, trace, created_at, last_step_at) VALUES "
            "(:id, :agent_id, :track, :client_key, :season, :engine_version, :action_version, "
            ":seed, :rng_seed, :back, :stake, :max_steps, :end_on_win, :max_free_moves, "
            ":reward_kind, CAST(:reward_weights AS jsonb), 'running', 0, :trace, :now, :now)"
        ),
        [
            {**r, "reward_weights": json.dumps(r["reward_weights"])
             if r["reward_weights"] is not None else None}
            for r in rows
        ],
    )  # fmt: skip


def commit_steps(
    conn: Connection, steps: Sequence[tuple[uuid.UUID, int, bytes]], now: datetime
) -> set[uuid.UUID]:
    """Advance running episodes by one step each: ``(id, t_before, packed index)``. Returns the
    ids it advanced; any other was moved on by someone else."""
    if not steps:
        return set()
    rows = conn.execute(
        text(
            "UPDATE episodes AS e SET t = e.t + 1, trace = e.trace || v.b, last_step_at = :now "
            "FROM unnest(CAST(:ids AS uuid[]), CAST(:ts AS integer[]), CAST(:bs AS bytea[])) "
            "AS v(id, t, b) WHERE e.id = v.id AND e.t = v.t AND e.status = 'running' "
            "RETURNING e.id"
        ),
        {
            "ids": [s[0] for s in steps],
            "ts": [s[1] for s in steps],
            "bs": [s[2] for s in steps],
            "now": now,
        },
    )
    return {r[0] for r in rows}


def end_episode(
    conn: Connection,
    episode_id: uuid.UUID,
    t_before: int,
    step: bytes | None,
    outcome: Outcome,
    tape: Sequence[str],
    engine_error: str | None,
    now: datetime,
) -> bool:
    """End a running episode, taking its final step (``step``) if it has one. False if someone
    else moved it on first."""
    advance = "t = t + 1, trace = trace || :b, " if step is not None else ""
    result = conn.execute(
        text(
            f"UPDATE episodes SET {advance}status = 'ended', last_step_at = :now, ended_at = :now, "
            "end_reason = :reason, won = :won, ante_reached = :ante, rounds_beaten = :rounds, "
            "refused = :refused, not_ported = :not_ported, attempted = CAST(:attempted AS jsonb), "
            "tape = CAST(:tape AS jsonb), final_state_hash = :hash, verified = :verified, "
            "engine_error = :error WHERE id = :id AND t = :t AND status = 'running'"
        ),
        {
            "b": step, "now": now, "reason": outcome.end_reason, "won": outcome.won,
            "ante": outcome.ante_reached, "rounds": outcome.rounds_beaten,
            "refused": outcome.refused, "not_ported": outcome.not_ported,
            "attempted": json.dumps(outcome.attempted) if outcome.attempted is not None else None,
            "tape": "[" + ",".join(tape) + "]", "hash": outcome.final_state_hash,
            "verified": outcome.verified, "error": engine_error, "id": episode_id, "t": t_before,
        },
    )  # fmt: skip
    return result.rowcount > 0


def running_of(conn: Connection, agent_id: uuid.UUID) -> list[EpisodeRow]:
    rows = conn.execute(
        text(
            f"SELECT {_EP_COLS} FROM episodes WHERE agent_id = :a AND status = 'running' "
            "ORDER BY created_at"
        ),
        {"a": agent_id},
    )
    return [_episode(r) for r in rows]


def idle_running(conn: Connection, before: datetime, limit: int = 100) -> list[EpisodeRow]:
    rows = conn.execute(
        text(
            f"SELECT {_EP_COLS} FROM episodes WHERE status = 'running' AND last_step_at < :before "
            "ORDER BY last_step_at LIMIT :limit"
        ),
        {"before": before, "limit": limit},
    )
    return [_episode(r) for r in rows]


def verified_episodes(
    conn: Connection, season: str, after: uuid.UUID | None, limit: int
) -> list[EpisodeRow]:
    """A page of the season's verified ended episodes, in id order after ``after``."""
    sql = (
        f"SELECT {_EP_COLS} FROM episodes WHERE season = :s AND status = 'ended' AND verified "
        "AND final_state_hash IS NOT NULL"
    )
    params: dict[str, Any] = {"s": season, "n": limit}
    if after is not None:
        sql += " AND id > :after"
        params["after"] = after
    return [_episode(r) for r in conn.execute(text(sql + " ORDER BY id LIMIT :n"), params)]


def get_episode(conn: Connection, episode_id: uuid.UUID) -> EpisodeRow | None:
    row = conn.execute(
        text(f"SELECT {_EP_COLS} FROM episodes WHERE id = :i"), {"i": episode_id}
    ).first()
    return _episode(row) if row else None


def ended_episodes_of(
    conn: Connection,
    agent_id: uuid.UUID,
    track: str | None,
    before: datetime | None,
    limit: int,
) -> list[EpisodeRow]:
    sql = f"SELECT {_EP_COLS} FROM episodes WHERE agent_id = :a AND status = 'ended'"
    params: dict[str, Any] = {"a": agent_id, "limit": limit}
    if track:
        sql += " AND track = :track"
        params["track"] = track
    if before:
        sql += " AND ended_at < :before"
        params["before"] = before
    sql += " ORDER BY ended_at DESC LIMIT :limit"
    return [_episode(r) for r in conn.execute(text(sql), params)]


def board_rows(
    conn: Connection, track: str, season: str, agent_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Per-agent sums over ended episodes, the input to the leaderboard statistics. A refused
    episode scores zero, as the repo's own evaluation scores it."""
    rows = conn.execute(
        text(
            "SELECT e.agent_id, count(*) AS n, "
            "sum(CASE WHEN e.end_reason = 'refused' THEN 0 ELSE e.rounds_beaten END) AS blinds, "
            "sum(CASE WHEN e.end_reason = 'refused' THEN 0 "
            "ELSE e.rounds_beaten * e.rounds_beaten END) AS blinds_sq, "
            "sum(CASE WHEN e.end_reason = 'refused' THEN 0 ELSE e.ante_reached END) AS ante, "
            "max(CASE WHEN e.end_reason = 'refused' THEN 0 ELSE e.ante_reached END) AS max_ante, "
            "sum(CASE WHEN e.won AND e.end_reason <> 'refused' THEN 1 ELSE 0 END) AS wins, "
            "sum(e.t) AS steps, "
            "sum(CASE WHEN e.end_reason = 'max_steps' THEN 1 ELSE 0 END) AS truncated, "
            "sum(CASE WHEN e.end_reason IN ('forfeit', 'idle') THEN 1 ELSE 0 END) AS forfeited, "
            "sum(CASE WHEN e.verified THEN 0 ELSE 1 END) AS unverified, "
            "max(e.ended_at) AS last_played "
            "FROM episodes e WHERE e.track = :track AND e.season = :season "
            "AND e.status = 'ended' "
            + ("AND e.agent_id = :agent " if agent_id is not None else "")
            + "GROUP BY e.agent_id"
        ),
        {"track": track, "season": season, "agent": agent_id},
    )
    return [dict(r._mapping) for r in rows]


def histogram(conn: Connection, agent_id: uuid.UUID, track: str, season: str) -> list[int]:
    """Ended episodes by blinds beaten (index = blinds), refused episodes counted at zero."""
    rows = conn.execute(
        text(
            "SELECT CASE WHEN end_reason = 'refused' THEN 0 ELSE rounds_beaten END AS b, "
            "count(*) FROM episodes WHERE agent_id = :a AND track = :t AND season = :s "
            "AND status = 'ended' GROUP BY 1 ORDER BY 1"
        ),
        {"a": agent_id, "t": track, "s": season},
    ).all()
    if not rows:
        return []
    out = [0] * (max(int(b or 0) for b, _ in rows) + 1)
    for b, n in rows:
        out[int(b or 0)] += int(n)
    return out


def agents_by_ids(conn: Connection, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Agent]:
    rows = conn.execute(
        text(f"SELECT {_AGENT_COLS} FROM {_AGENT_FROM} WHERE a.id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": list(ids)},
    )
    return {r[0]: Agent(*r) for r in rows}
