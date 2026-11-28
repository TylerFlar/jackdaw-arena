"""``ArenaEnv``: a Gymnasium env that plays Arena episodes, a drop-in for
``jackdaw.env.BalatroGymnasiumEnv``.

Same observation dict, ``Discrete(500)`` actions, ``action_masks()`` for MaskablePPO, and the
same ``balatro/*`` keys in the final step's info. Two differences come from evaluating on the
server: the seed is chosen there (``reset(seed=...)`` is ignored), and every episode counts.
Resetting or closing in the middle of an episode forfeits it, scored as far as it got. The one
that doesn't count is a void episode, which a deploy can end: its step comes back truncated, with
``arena/void`` in the info and none of the ``balatro/*`` keys.

As with ``BalatroGymnasiumEnv``, ``step_factored(action)`` takes an action instead of an index
(one the table's sample may have left out), ``player_view()`` returns what a player sees, and
with jackdaw installed ``view_game()`` builds a game from it to plan on.
"""

from __future__ import annotations

import warnings
from typing import Any

import gymnasium
import numpy as np

from jackdaw_arena.client import ArenaClient, is_void, wire_action
from jackdaw_arena.view import ViewGame


class ArenaEnv(gymnasium.Env):
    metadata: dict[str, Any] = {"render_modes": []}

    def __init__(
        self,
        client: ArenaClient | None = None,
        track: str = "red-1",
        reward: str = "sparse",
        weights: dict[str, float] | None = None,
        view: bool = False,
    ) -> None:
        """``view``: every reset and step also fetches the player view, for :meth:`player_view`
        (which otherwise asks the server for it)."""
        super().__init__()
        self.client = client or ArenaClient()
        self.track, self.reward, self.weights = track, reward, weights
        self.view = view
        self._view: dict[str, Any] | None = None
        spec = self.client.spec()
        self.spec = spec
        self.observation_space = spec.observation_space()
        self.action_space = spec.action_space()
        self.action_version = spec.action_version
        self.metadata = {**self.metadata, "action_version": spec.action_version}
        self.episode_id: str | None = None
        self._t = 0
        self._n_actions = 0
        self._running = False
        self._obs: dict[str, np.ndarray] | None = None
        self._view_game: ViewGame | None = None

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        super().reset(seed=seed)
        if seed is not None:
            warnings.warn(
                "Arena seeds are chosen by the server; reset(seed=...) is ignored",
                stacklevel=2,
            )
        if self._running and self.episode_id is not None:
            warnings.warn(
                "resetting mid-episode forfeits it (every Arena episode counts)", stacklevel=2
            )
            self.client.forfeit(self.episode_id)
        (ep,) = self.client.create(1, self.track, self.reward, self.weights, view=self.view)
        if self._view_game is not None:
            self._view_game.reset()
        self.episode_id = ep["id"]
        self._t, self._n_actions, self._running = ep["t"], ep["n_actions"], True
        self._view = ep.get("view")
        self._obs = self.spec.decode(ep["obs"])
        return self._obs, {
            "action_mask": self.action_masks(),
            "arena/episode_id": self.episode_id,
        }

    def step(self, action: int) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        return self._step(int(action))

    def step_factored(
        self, action: Any
    ) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        """:meth:`step` with a factored action instead of an index (jackdaw's
        ``FactoredAction``, a mapping, or ``(action_type, entity_target, card_target)``): any
        action the env offers, whether or not the table's sample holds it, as
        ``BalatroGymnasiumEnv.step_factored``. One it doesn't offer raises ``RuntimeError``
        (``illegal_action``) and changes nothing."""
        return self._step(wire_action(action))

    def player_view(self) -> dict[str, Any]:
        """What a player sees of the run now, as ``BalatroGymnasiumEnv.player_view()`` returns
        it (``jackdaw.player_view/1``), with the last hand's scoring events."""
        if self._view is None:
            if not self._running or self.episode_id is None:
                raise RuntimeError("no view: the episode has ended (use view=True to keep one)")
            self._view = self.client.get(self.episode_id, view=True)["view"]
        assert self._view is not None
        return self._view

    def view_game(self) -> Any:
        """The run as :meth:`player_view` shows it, as a jackdaw ``Game`` to plan on: every
        field a player sees is the view's, the hidden parts are stand-ins (the draw pile's
        order, face-down cards, the RNG), and it's kept across the episode with the actions
        taken, so it knows what they taught and no view lists (the consumables used, the cards
        played this ante). jackdaw's ``BalatroGymnasiumEnv.view_game()`` builds the same game
        from the same view, so an agent plans with the same code locally and here. A copy: step
        it as you like.

        It needs jackdaw installed (0.3.2 or later), and plans best with the Arena's own
        release (``spec.engine_version``), whose actions are the ones the Arena offers: it warns
        when the installed jackdaw's action space isn't the Arena's. From the first call on,
        every step also fetches the view (as ``view=True`` does), to keep the game. Take
        factored steps (:meth:`step_factored`): an index leaves no action to step the game with,
        as the table is the server's, and the next game then builds on the last one as it
        was."""
        if self._view_game is None:
            self._view_game = ViewGame(self.spec)
            self.view = True
        return self._view_game.game(self.player_view())

    def _step(
        self, action: int | dict[str, Any]
    ) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        if not self._running or self.episode_id is None:
            raise RuntimeError("call reset() first: the episode has ended")
        if self._view_game is not None:
            self._view_game.before_step(self.player_view())
        (r,) = self.client.step([(self.episode_id, self._t, action)], view=self.view)
        if not r["ok"]:
            if r["error"] == "ended" and is_void(r.get("final")):
                # A deploy voided it: the step wasn't taken, and the episode counts nowhere.
                self._running, self._n_actions, self._view = False, 0, None
                info = {"action_mask": self.action_masks(), "arena/episode_id": self.episode_id,
                        "arena/void": True, "arena/final": r["final"]}  # fmt: skip
                assert self._obs is not None
                return self._obs, 0.0, False, True, info
            raise RuntimeError(f"step refused: {r['error']} (t={r.get('t')})")
        if self._view_game is not None:
            self._view_game.stepped(action)
        self._t, self._n_actions = r["t"], r["n_actions"]
        self._view = r.get("view")
        info: dict[str, Any] = {"action_mask": None, "arena/episode_id": self.episode_id}
        final = r["final"]
        if final is not None:
            self._running = False
            self._n_actions = 0
            info.update(final_info(final))
        info["action_mask"] = self.action_masks()
        self._obs = self.spec.decode(r["obs"])
        return self._obs, r["reward"], r["terminated"], r["truncated"], info

    def action_masks(self) -> np.ndarray:
        return self.spec.mask(self._n_actions)

    def close(self) -> None:
        if self._running and self.episode_id is not None:
            self.client.forfeit(self.episode_id)
            self._running = False


def final_info(final: dict[str, Any]) -> dict[str, Any]:
    """The end-of-episode keys ``BalatroGymnasiumEnv`` sets, plus the Arena's."""
    info: dict[str, Any] = {
        "balatro/ante_reached": final["ante_reached"],
        "balatro/rounds_beaten": final["rounds_beaten"],
        "balatro/won": final["won"],
        "arena/seed": final["seed"],
        "arena/final": final,
    }
    if final.get("refused"):
        info["balatro/refused"] = final["refused"]
    if final.get("not_ported"):
        info["balatro/not_ported"] = final["not_ported"]
    return info
