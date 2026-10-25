"""Leaderboard statistics from per-agent sums.

The rank key is the mean number of blinds beaten, the repo's own headline metric. It comes with
its standard error and a normal 95% interval. Win rate gets a Wilson interval: at the rates
agents reach today (near zero), the normal one is useless. An agent is ranked only once all of
its budgeted episodes on the track have ended, so stopping while ahead isn't possible.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

from sqlalchemy import Connection

from arena.db import repo

Z95 = 1.959963984540054


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if successes == 0 else max(0.0, centre - half)
    hi = 1.0 if successes == n else min(1.0, centre + half)
    return (lo, hi)


def stats(row: dict[str, Any]) -> dict[str, Any]:
    n = int(row["n"])
    blinds, blinds_sq = float(row["blinds"] or 0), float(row["blinds_sq"] or 0)
    mean = blinds / n
    sem = ci = None
    if n > 1:
        var = max(0.0, (blinds_sq - blinds * blinds / n) / (n - 1))
        sem = math.sqrt(var / n)
        ci = (mean - Z95 * sem, mean + Z95 * sem)
    wins = int(row["wins"] or 0)
    return {
        "n": n,
        "blinds_mean": mean,
        "blinds_sem": sem,
        "blinds_ci95": ci,
        "ante_mean": float(row["ante"] or 0) / n,
        "max_ante": int(row["max_ante"] or 0),
        "win_rate": wins / n,
        "win_ci95": wilson(wins, n),
        "length_mean": float(row["steps"] or 0) / n,
        "truncated": int(row["truncated"] or 0) / n,
        "forfeited": int(row["forfeited"] or 0) / n,
        "unverified": int(row["unverified"] or 0),
    }


def agent_summary(a: repo.Agent) -> dict[str, Any]:
    return {
        "slug": a.slug, "name": a.name, "description": a.description, "url": a.url,
        "kind": a.kind, "owner": {"login": a.owner_login, "avatar_url": a.owner_avatar},
        "created_at": a.created_at,
    }  # fmt: skip


def leaderboard(conn: Connection, track: repo.Track, season: str) -> dict[str, Any]:
    rows = repo.board_rows(conn, track.key, season)
    agents = repo.agents_by_ids(conn, [r["agent_id"] for r in rows])
    ranked, provisional, house = [], [], []
    for r in rows:
        agent = agents.get(r["agent_id"])
        if agent is None or agent.hidden or agent.unlisted:
            continue
        entry = {"rank": None, "agent": agent_summary(agent), "stats": stats(r)}
        if agent.kind == "house":
            house.append(entry)
        elif entry["stats"]["n"] >= track.episodes_per_agent:
            ranked.append(entry)
        else:
            provisional.append(entry)
    key = lambda e: (-e["stats"]["blinds_mean"], -e["stats"]["win_rate"], e["agent"]["slug"])  # noqa: E731
    ranked.sort(key=key)
    for i, e in enumerate(ranked, start=1):
        e["rank"] = i
    provisional.sort(key=lambda e: (-e["stats"]["n"], e["agent"]["slug"]))
    house.sort(key=key)
    return {
        "track": track.key,
        "season": season,
        "k": track.episodes_per_agent,
        "ranked": ranked,
        "provisional": provisional,
        "house": house,
    }


def agent_tracks(
    conn: Connection, agent_id: uuid.UUID, tracks: list[repo.Track], season: str
) -> tuple[dict[str, Any], dict[str, list[int]]]:
    """Per-track stats and blinds-beaten histograms for one agent."""
    out: dict[str, Any] = {}
    hist: dict[str, list[int]] = {}
    for t in tracks:
        rows = repo.board_rows(conn, t.key, season, agent_id)
        out[t.key] = stats(rows[0]) if rows else None
        hist[t.key] = repo.histogram(conn, agent_id, t.key, season)
    return out, hist
