"""Replay v2 (``/api/episodes/{id}/replay``): the frames of ``/frames`` with card ids and what
each action did, checked against the frames around it."""

from __future__ import annotations

import math

from sqlalchemy import text

from arena.house import run_house


def _same(a, b) -> bool:
    return a == b or (
        isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b)
    )


def _ids(f: dict) -> list[int]:
    shop = f["shop"]
    areas = [f["hand"], f["jokers"], f["consumables"], f["pack"]]
    areas += [shop["cards"], shop["vouchers"], shop["boosters"]]
    return [c["id"] for area in areas for c in area]


def _ended(client) -> str:
    run_house(client.app.state.episodes, "smart", episodes=1)
    with client.app.state.engine.connect() as conn:
        return str(conn.execute(text("SELECT id FROM episodes")).scalar_one())


def test_replay_frames_follow_cards_and_explain_each_action(client):
    eid = _ended(client)
    r = client.get(f"/api/episodes/{eid}/replay")
    assert "immutable" in r.headers["cache-control"]
    doc = r.json()
    frames = doc["frames"]
    assert doc["total"] == len(frames) and frames[-1]["action"] is None
    v1 = client.get(f"/api/episodes/{eid}/frames").json()["frames"]
    plays = cash_outs = 0
    for f, old in zip(frames, v1, strict=True):
        # Everything /frames has, unchanged.
        assert {k: v for k, v in f.items() if k in old and k not in _NEW} == {
            k: v for k, v in old.items() if k not in _NEW
        }
        ids = _ids(f)
        assert len(ids) == len(set(ids)), f"frame {f['i']}: an id twice"
        assert f["limits"]["hand"] >= 1 and f["deck_size"] == old["deck_size"]
    for f, nxt in zip(frames, frames[1:], strict=False):
        out = f["outcome"]
        kind = f["action"][0]
        if kind == "PlayHand":
            play = out["play"]
            hand_ids = {c["id"] for c in f["hand"]}
            assert set(play["played"]) <= hand_ids
            assert set(play["scoring"]) <= set(play["played"])
            assert not set(play["played"]) & {c["id"] for c in nxt["hand"]}
            last = play["events"][-1]
            score = nxt["last_score"]
            assert _same(last["hand_chips"], score["chips"]) and _same(
                last["hand_mult"], score["mult"]
            )
            assert play["hand"] == score["hand_type"]
            plays += 1
        elif out is not None:
            assert "play" not in out or out["play"] is None
        if kind == "CashOut":
            assert out["cash_out"] == nxt["dollars"] - f["dollars"] > 0
            cash_outs += 1
    assert plays > 3 and cash_outs > 0

    part = client.get(f"/api/episodes/{eid}/replay", params={"from": 5, "limit": 4}).json()
    assert part["frames"] == frames[5:9]


def test_the_blind_select_row_names_its_keys(client):
    eid = _ended(client)
    first = client.get(f"/api/episodes/{eid}/replay", params={"limit": 1}).json()["frames"][0]
    row = first["blinds"]
    assert row["small"]["key"] == "bl_small" and row["big"]["key"] == "bl_big"
    assert row["boss"]["key"].startswith("bl_")
    assert row["small"]["tag_key"].startswith("tag_")


# Fields that replay frames carry beyond /frames, or carry differently (cards have ids).
_NEW = {
    "hand", "jokers", "consumables", "shop", "pack", "blinds", "last_score", "limits",
    "reroll_cost", "pack_info", "outcome",
}  # fmt: skip
