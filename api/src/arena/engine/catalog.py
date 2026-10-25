"""Display names for the game's keys, from jackdaw's data tables (no game art or text)."""

from __future__ import annotations

from functools import cache
from typing import Any

from jackdaw.engine import data

RANK_SHORT = {"Jack": "J", "Queen": "Q", "King": "K", "Ace": "A"}
SUIT_GLYPH = {"Hearts": "♥", "Diamonds": "♦", "Clubs": "♣", "Spades": "♠"}


@cache
def catalog() -> dict[str, Any]:
    centers = {
        k: {"name": v.get("name", k), "set": v.get("set"), "rarity": v.get("rarity")}
        for k, v in data.load("centers").items()
    }
    blinds = {
        k: {"name": v.get("name", k), "boss": bool(v.get("boss"))}
        for k, v in data.load("blinds").items()
    }
    tags = {k: {"name": v.get("name", k)} for k, v in data.load("tags").items()}
    return {"centers": centers, "blinds": blinds, "tags": tags}


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
