"""Replay frames: what the player saw at each step of an ended episode, and what they did.

A frame is built by replaying the episode's tape on a fresh run and reading jackdaw's cheap
per-section views. Face-down cards stay face down: the replay shows the player's view, not the
engine's.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from jackdaw import _core
from jackdaw.core import Game
from jackdaw.core.views import CardView

from arena.engine.catalog import card_label, name_of
from arena.engine.live import RunSpec


def _card(c: CardView) -> dict[str, Any]:
    if c.face_down:
        return {
            "face_down": True, "key": None, "front": None, "suit": None, "rank": None,
            "edition": None, "seal": None, "debuff": c.debuff, "cost": None, "sell_cost": None,
            "eternal": False, "perishable": False, "rental": False,
        }  # fmt: skip
    return {
        "face_down": False, "key": c.key, "front": c.front, "suit": c.suit, "rank": c.rank,
        "edition": c.edition, "seal": c.seal, "debuff": c.debuff, "cost": c.cost,
        "sell_cost": c.sell_cost, "eternal": c.eternal, "perishable": c.perishable,
        "rental": c.rental,
    }  # fmt: skip


def _blinds(raw: Any) -> dict[str, Any] | None:
    """The blind-select row from BalatroBot's gamestate (names, targets, skip tags). Its JSON
    writes empty objects as ``[]``, so normalise those."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for slot in ("small", "big", "boss"):
        b = raw.get(slot)
        if isinstance(b, dict):
            out[slot] = {
                "name": b.get("name"), "status": b.get("status"), "score": b.get("score"),
                "tag": b.get("tag_name") or None,
            }  # fmt: skip
    return out or None


def frame(game: Game) -> dict[str, Any]:
    blind = game.blind
    last = game.last_score
    view = json.loads(game._g.bot_view())
    return {
        "phase": game.phase.value,
        "ante": game.ante,
        "round": game.round,
        "dollars": game.dollars,
        "chips": game.chips,
        "hands_left": game.hands_left,
        "discards_left": game.discards_left,
        "blind": None
        if blind is None
        else {
            "key": blind.key,
            "name": name_of(blind.key),
            "chips": blind.chips,
            "boss": blind.boss,
            "disabled": blind.disabled,
            "dollars": blind.dollars,
        },  # fmt: skip
        "blinds": _blinds(view.get("blinds")),
        "hand": [_card(c) for c in game.hand],
        "jokers": [_card(c) for c in game.jokers],
        "consumables": [_card(c) for c in game.consumables],
        "shop": {
            "cards": [_card(c) for c in game.shop_jokers],
            "vouchers": [_card(c) for c in game.shop_vouchers],
            "boosters": [_card(c) for c in game.shop_boosters],
        },
        "pack": [_card(c) for c in game.pack_cards],
        "tags": [{"key": t, "name": name_of(t)} for t in game.tags],
        "last_score": None
        if last is None
        else {
            "hand_type": last.hand_type,
            "chips": last.chips,
            "mult": last.mult,
            "total": last.total,
            "debuffed": last.debuffed,
        },  # fmt: skip
        "deck_size": len(game.deck),
        "discard_size": len(game.discard_pile),
    }


def describe(action: list[Any], f: dict[str, Any]) -> str:
    """Plain English for a tape action, read against the frame it was taken in."""
    kind = action[0]

    def cards(area: list[dict[str, Any]], idx: Sequence[int] | None) -> str:
        return " ".join(card_label(area[i]) for i in (idx or []) if i < len(area))

    def one(area: list[dict[str, Any]], i: int) -> dict[str, Any]:
        return area[i] if i < len(area) else {"key": None}

    shop = f["shop"]
    match kind:
        case "SelectBlind":
            on_deck = next(
                (b for b in (f.get("blinds") or {}).values() if b.get("status") == "SELECT"), None
            )
            return (
                f"Select {on_deck['name']}" if on_deck and on_deck.get("name") else "Select blind"
            )
        case "SkipBlind":
            on_deck = next(
                (b for b in (f.get("blinds") or {}).values() if b.get("status") == "SELECT"), None
            )
            tag = on_deck.get("tag") if on_deck else None
            return f"Skip blind for {tag}" if tag else "Skip blind"
        case "RerollBoss":
            return "Reroll the boss"
        case "PlayHand":
            return f"Play {cards(f['hand'], action[1])}"
        case "Discard":
            return f"Discard {cards(f['hand'], action[1])}"
        case "BuyCard":
            c = one(shop["cards"], action[1])
            return f"Buy {card_label(c)}" + (f" (${c['cost']:g})" if c.get("cost") else "")
        case "BuyAndUse":
            return f"Buy and use {card_label(one(shop['cards'], action[1]))}"
        case "SellCard":
            area = f["jokers"] if action[1] == "jokers" else f["consumables"]
            c = one(area, action[2])
            return f"Sell {card_label(c)}" + (
                f" (+${c['sell_cost']:g})" if c.get("sell_cost") else ""
            )
        case "UseConsumable":
            c = one(f["consumables"], action[1])
            targets = cards(f["hand"], action[2] if len(action) > 2 else None)
            return f"Use {card_label(c)}" + (f" on {targets}" if targets else "")
        case "RedeemVoucher":
            return f"Redeem {card_label(one(shop['vouchers'], action[1]))}"
        case "OpenBooster":
            return f"Open {card_label(one(shop['boosters'], action[1]))}"
        case "PickPackCard":
            c = one(f["pack"], action[1])
            targets = cards(f["hand"], action[2] if len(action) > 2 else None)
            return f"Take {card_label(c)}" + (f" on {targets}" if targets else "")
        case "SkipPack":
            return "Skip the pack"
        case "Reroll":
            return "Reroll the shop"
        case "NextRound":
            return "Leave the shop"
        case "CashOut":
            return "Cash out"
        case "SortHand":
            return f"Sort hand by {action[1]}"
        case "SwapHandLeft" | "SwapHandRight":
            side = "left" if kind.endswith("Left") else "right"
            return f"Move {card_label(one(f['hand'], action[1]))} {side}"
        case "SwapJokersLeft" | "SwapJokersRight":
            side = "left" if kind.endswith("Left") else "right"
            return f"Move {card_label(one(f['jokers'], action[1]))} {side}"
    return kind


def frames(
    spec: RunSpec, tape: Sequence[Any], start: int = 0, limit: int = 200
) -> list[dict[str, Any]]:
    """Frames ``start`` to ``start + limit - 1`` of an episode. Frame ``i`` is the state before
    the ``i``-th tape action (with that action described); the last is the final state."""
    game = Game(_core.Game.new(spec.back, spec.stake, spec.seed, spec.challenge))
    out: list[dict[str, Any]] = []
    stop = min(len(tape) + 1, start + limit)
    for i in range(stop):
        action = tape[i] if i < len(tape) else None
        if i >= start:
            f = frame(game)
            f["i"] = i
            f["action"] = action
            f["description"] = describe(action, f) if action is not None else None
            out.append(f)
        if action is not None:
            game._g.step(json.dumps(action))
    return out
