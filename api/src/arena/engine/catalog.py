"""Display names and sprite cells for the game's keys, from jackdaw's data tables. Only the
numbers: the art itself isn't part of the Arena."""

from __future__ import annotations

from functools import cache
from typing import Any

from jackdaw.engine import data

RANK_SHORT = {"Jack": "J", "Queen": "Q", "King": "K", "Ace": "A"}
SUIT_GLYPH = {"Hearts": "♥", "Diamonds": "♦", "Clubs": "♣", "Spades": "♠"}


def _cell(pos: Any) -> list[int] | None:
    return [int(pos["x"]), int(pos["y"])] if isinstance(pos, dict) else None


@cache
def catalog() -> dict[str, Any]:
    centers = {
        k: {
            "name": v.get("name", k),
            "set": v.get("set"),
            "rarity": v.get("rarity"),
            "pos": _cell(v.get("pos")),
            "soul": _cell(v.get("soul_pos")),
        }
        for k, v in data.load("centers").items()
    }
    blinds = {
        k: {"name": v.get("name", k), "boss": bool(v.get("boss")), "pos": _cell(v.get("pos"))}
        for k, v in data.load("blinds").items()
    }
    tags = {
        k: {"name": v.get("name", k), "pos": _cell(v.get("pos"))}
        for k, v in data.load("tags").items()
    }
    # Keyed by level, as tracks store them. The data names them "White Chip"; the game's text
    # says "White Stake".
    stakes = {
        str(v["stake_level"]): {
            "name": v["name"].removesuffix(" Chip") + " Stake",
            "pos": _cell(v.get("pos")),
        }
        for v in data.load("stakes").values()
    }
    return {"centers": centers, "blinds": blinds, "tags": tags, "stakes": stakes}


def name_of(key: str | None) -> str:
    if not key:
        return "?"
    c = catalog()
    for table in ("centers", "blinds", "tags"):
        if key in c[table]:
            return c[table][key]["name"]
    return key


def card_label(card: dict[str, Any]) -> str:
    """``K♠`` for a playing card, the name for anything else, ``??`` face down."""
    if card.get("face_down"):
        return "??"
    if card.get("rank") and card.get("suit"):
        rank = RANK_SHORT.get(card["rank"], card["rank"])
        return f"{rank}{SUIT_GLYPH.get(card['suit'], card['suit'][0])}"
    return name_of(card.get("key"))
