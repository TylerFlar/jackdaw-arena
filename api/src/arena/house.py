"""House baselines: agents the Arena runs itself, through the same service and records as anyone's.

``random`` picks uniformly among the legal actions. ``smart`` is jackdaw's hand-written
``smart_agent``, choosing from the same action table the way ``examples/evaluate_agents.py``
does. It reads the run directly, face-down cards included, so it can only run here and is
listed as a privileged baseline, never ranked.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import numpy as np
from jackdaw.core import Game
from jackdaw.engine import actions as A
from jackdaw.env import FactoredAction, engine_action_to_factored
from jackdaw.env.rust_gym import factored_from_parts

from arena.db import repo
from arena.engine.live import LiveEpisode
from arena.services.episodes import EpisodeService, StepItem

HOUSE_LOGIN = "jackdaw-house"
POLICIES = ("random", "smart")

Chooser = Callable[[LiveEpisode], int]


def random_chooser(seed: int) -> Chooser:
    rng = np.random.default_rng(seed)
    return lambda live: int(rng.integers(live.n_actions))


def smart_chooser() -> Chooser:
    from jackdaw.cli.smart_agent import smart_agent

    def with_forced_card(action: Any, game: Game) -> Any:
        # Cerulean Bell: vanilla always selects the forced card.
        if not isinstance(action, (A.PlayHand, A.Discard)):
            return action
        forced = [i for i, c in enumerate(game.hand) if c.ability.get("forced_selection")]
        if not forced or forced[0] in action.card_indices:
            return action
        kept = list(action.card_indices)[:4]
        return type(action)(card_indices=tuple(sorted({*kept, forced[0]})))

    def closest(table: list[FactoredAction], wanted: FactoredAction) -> int:
        want = set(wanted.card_target or ())
        best, best_score = 0, None
        for i, a in enumerate(table):
            if a.action_type != wanted.action_type:
                continue
            have = set(a.card_target or ())
            score = (a.entity_target == wanted.entity_target, len(want & have) - len(want ^ have))
            if best_score is None or score > best_score:
                best, best_score = i, score
        return best

    def choose(live: LiveEpisode) -> int:
        game = Game(live.env.game())
        table = [factored_from_parts(p) for p in live.env.action_table()]
        action = with_forced_card(smart_agent(game, game.legal_actions()), game)
        wanted = engine_action_to_factored(action)
        if wanted.card_target == ():
            wanted = FactoredAction(wanted.action_type, None, wanted.entity_target)
        return table.index(wanted) if wanted in table else closest(table, wanted)

    return choose


def house_agent(service: EpisodeService, policy: str) -> repo.Agent:
    """The house agent for ``policy``, created on first use."""
    slug = f"house-{policy}"
    now = service.clock()
    with service.engine.begin() as conn:
        agent = repo.agent_by_slug(conn, slug)
        if agent is not None:
            return agent
        user = repo.upsert_identity_user(
            conn, "house", HOUSE_LOGIN, HOUSE_LOGIN, "Jackdaw Arena", None, False, now
        )
        description = {
            "random": "Uniform over the legal actions.",
            "smart": "jackdaw's hand-written heuristic agent. Reads face-down cards, so it is a "
            "privileged baseline, not a competitor.",
        }[policy]
        aid = repo.create_agent(
            conn, user.id, slug, f"{policy} (house)", description,
            "https://github.com/TylerFlar/jackdaw-balatro", "house", False, now,
        )  # fmt: skip
        agent = repo.agent_by_id(conn, aid)
    assert agent is not None
    return agent


def run_house(
    service: EpisodeService,
    policy: str,
    episodes: int,
    track: str = "red-1",
    batch: int = 32,
    seed: int = 0,
) -> dict[str, Any]:
    """Play ``episodes`` episodes with a house policy; return the summary the repo's own
    evaluation prints (means over episodes)."""
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}; expected one of {', '.join(POLICIES)}")
    agent = house_agent(service, policy)
    choose = random_chooser(seed) if policy == "random" else smart_chooser()
    finals: list[dict[str, Any]] = []
    remaining = episodes
    while remaining > 0:
        n = min(batch, remaining)
        remaining -= n
        created = service.create(agent, track, [uuid.uuid4() for _ in range(n)])
        state = {e["id"]: (e["t"],) for e in created if e["status"] == "running"}
        while state:
            items = []
            for eid, (t,) in state.items():
                live = service.live(agent, eid)
                items.append(StepItem(eid, t, choose(live)))
            for r in service.step(agent, items):
                if not r["ok"]:
                    raise RuntimeError(f"house step failed: {r}")
                if r["final"] is not None:
                    finals.append(r["final"])
                    del state[r["id"]]
                else:
                    state[r["id"]] = (r["t"],)
    # As in the repo's evaluation, a refused episode (an env bug) scores zero.
    blinds = np.array(
        [0 if f["end_reason"] == "refused" else f["rounds_beaten"] for f in finals], dtype=float
    )
    return {
        "agent": agent.slug,
        "episodes": len(finals),
        "blinds_beaten": float(blinds.mean()) if len(blinds) else 0.0,
        "blinds_beaten_sem": float(blinds.std(ddof=1) / np.sqrt(len(blinds)))
        if len(blinds) > 1
        else None,
        "ante_reached": float(np.mean([f["ante_reached"] for f in finals])) if finals else 0.0,
        "win_rate": float(np.mean([bool(f["won"]) for f in finals])) if finals else 0.0,
        "length": float(np.mean([f["length"] for f in finals])) if finals else 0.0,
        "verified": all(f["verified"] for f in finals),
    }
