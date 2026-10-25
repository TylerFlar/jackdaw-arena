"""Replay frames with what a replay needs to show each action play out.

Frame ``i`` is the state before the ``i``-th tape action, as ``/frames`` gives it, with:

- every card's ``id`` (its sort id), so a card can be followed from one area to another;
- the blind-select row's keys, the areas' limits, the reroll cost and the open pack;
- ``outcome``: what the frame's action did. A play's scoring, event by event (jackdaw's
  ``Game.last_play``), the money a cash out paid, and the hand levels any action changed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import cache
from typing import Any

from jackdaw import _core
from jackdaw.core import Game
from jackdaw.core.views import CardView, ScoreEvent

from arena.engine.catalog import catalog, name_of
from arena.engine.frames import _blinds, _card, describe, num
from arena.engine.live import RunSpec


def _with_id(c: CardView) -> dict[str, Any]:
    return {"id": c.sort_id, **_card(c)}


@cache
def _keys(table: str) -> dict[str, str]:
    """A catalog table's keys by name: the blind-select row names its blinds and tags."""
    return {v["name"]: k for k, v in catalog()[table].items()}


def _blind_row(raw: Any) -> dict[str, Any] | None:
    row = _blinds(raw)
    for b in (row or {}).values():
        b["key"] = _keys("blinds").get(b["name"] or "")
        b["tag_key"] = _keys("tags").get(b["tag"] or "")
    return row


def _event(e: ScoreEvent) -> dict[str, Any]:
    return {
        "kind": e.kind, "card": e.card, "target": e.target, "chips": num(e.chips),
        "mult": num(e.mult), "x_mult": num(e.x_mult), "dollars": num(e.dollars),
        "level": num(e.level), "swap": e.swap, "shattered": e.shattered,
        "hand_chips": num(e.hand_chips), "hand_mult": num(e.hand_mult),
    }  # fmt: skip


def frame(game: Game, view: dict[str, Any]) -> dict[str, Any]:
    """The state, read from the run and from BalatroBot's view of it (``view``)."""
    blind = game.blind
    if blind is not None and not blind.key:
        blind = None  # between rounds the run's blind is cleared
    last = game.last_score
    pack = game._view("pack") if game.phase.value == "pack_opening" else None
    return {
        "phase": game.phase.value,
        "ante": game.ante,
        "round": game.round,
        "dollars": game.dollars,
        "chips": num(game.chips),
        "hands_left": game.hands_left,
        "discards_left": game.discards_left,
        "blind": None
        if blind is None
        else {
            "key": blind.key,
            "name": name_of(blind.key),
            "chips": num(blind.chips),
            "boss": blind.boss,
            "disabled": blind.disabled,
            "dollars": num(blind.dollars),
        },  # fmt: skip
        "blinds": _blind_row(view.get("blinds")),
        "hand": [_with_id(c) for c in game.hand],
        "jokers": [_with_id(c) for c in game.jokers],
        "consumables": [_with_id(c) for c in game.consumables],
        "shop": {
            "cards": [_with_id(c) for c in game.shop_jokers],
            "vouchers": [_with_id(c) for c in game.shop_vouchers],
            "boosters": [_with_id(c) for c in game.shop_boosters],
        },
        "pack": [_with_id(c) for c in game.pack_cards],
        "pack_info": None
        if not pack
        else {"kind": pack["kind"], "choices": pack["choices_remaining"]},
        "tags": [{"key": t, "name": name_of(t)} for t in game.tags],
        "last_score": None
        if last is None
        else {
            "hand_type": last.hand_type,
            "chips": num(last.chips),
            "mult": num(last.mult),
            "total": num(last.total),
            "dollars": num(last.dollars),
            "debuffed": last.debuffed,
        },  # fmt: skip
        "limits": {
            "hand": view["hand"]["limit"],
            "jokers": view["jokers"]["limit"],
            "consumables": view["consumables"]["limit"],
        },
        "reroll_cost": num(view["round"]["reroll_cost"]),
        "deck_size": view["cards"]["count"],
        "discard_size": len(game.discard_pile),
    }


def outcome(
    game: Game, action: list[Any], dollars: float, before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any] | None:
    """What ``action`` did: ``game`` and ``after`` are the run after it, ``dollars`` and
    ``before`` before it."""
    out: dict[str, Any] = {}
    play = game.last_play if action[0] == "PlayHand" else None
    if play is not None:
        out["play"] = {
            "hand": play.hand, "level": num(play.level), "played": list(play.played),
            "scoring": list(play.scoring), "events": [_event(e) for e in play.events],
        }  # fmt: skip
    if action[0] == "CashOut":
        out["cash_out"] = num(game._g.dollars - dollars)
    old = before["hands"]
    ups = [
        {"hand": name, "level": h["level"], "chips": num(h["chips"]), "mult": num(h["mult"])}
        for name, h in after["hands"].items()
        if name in old and h["level"] != old[name]["level"]
    ]
    if ups:
        out["level_ups"] = ups
    return out or None


def replay(
    spec: RunSpec, tape: Sequence[Any], start: int = 0, limit: int = 200
) -> list[dict[str, Any]]:
    """Frames ``start`` to ``start + limit - 1`` of an episode, each with its action's
    outcome; the last frame is the final state."""
    game = Game(_core.Game.new(spec.back, spec.stake, spec.seed, spec.challenge))
    game.record_scoring = True
    out: list[dict[str, Any]] = []
    view: dict[str, Any] | None = None
    for i in range(min(len(tape) + 1, start + limit)):
        action = tape[i] if i < len(tape) else None
        f: dict[str, Any] | None = None
        if i >= start:
            if view is None:
                view = json.loads(game._g.bot_view())
            f = frame(game, view)
            f["i"] = i
            f["action"] = action
            f["description"] = describe(action, f) if action is not None else None
            f["outcome"] = None
            out.append(f)
        if action is None:
            break
        dollars = game._g.dollars
        game._g.step(json.dumps(action))
        if f is not None and view is not None:
            after = json.loads(game._g.bot_view())
            f["outcome"] = outcome(game, action, dollars, view, after)
            view = after
    return out
