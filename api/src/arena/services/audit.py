"""Replay a season's ended episodes with the running engine.

A jackdaw release joins a season only if it plays the same game: every verified episode must
replay from its seed and tape to the final state the server recorded. Deploys run this when
the engine changes, before the new version takes traffic.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine

from arena.db import repo
from arena.engine.live import verify_tape
from arena.engine.spec import ENGINE_VERSION


def audit(engine: Engine, season: str, *, batch: int = 200, examples: int = 20) -> dict[str, Any]:
    checked = 0
    wrong: list[str] = []
    after = None
    while True:
        with engine.connect() as conn:
            rows = repo.verified_episodes(conn, season, after, batch)
        if not rows:
            break
        for row in rows:
            checked += 1
            try:
                final = verify_tape(row.spec, [json.dumps(a) for a in row.tape or []])
            except Exception as exc:  # noqa: BLE001 - an action this engine won't play
                wrong.append(f"{row.id}: {type(exc).__name__}")
                continue
            if final != row.final_state_hash:
                wrong.append(f"{row.id}: a different final state")
        after = rows[-1].id
    return {
        "ok": not wrong,
        "season": season,
        "engine": ENGINE_VERSION,
        "checked": checked,
        "failed": len(wrong),
        "examples": wrong[:examples],
    }
