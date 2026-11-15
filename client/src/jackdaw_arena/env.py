"""``ArenaEnv``: a Gymnasium env that plays Arena episodes, a drop-in for
``jackdaw.env.BalatroGymnasiumEnv``.

Same observation dict, ``Discrete(500)`` actions, ``action_masks()`` for MaskablePPO, and the
same ``balatro/*`` keys in the final step's info. Two differences come from evaluating on the
server: the seed is chosen there (``reset(seed=...)`` is ignored), and every episode counts.
Resetting or closing in the middle of an episode forfeits it, scored as far as it got.
"""

from __future__ import annotations

import warnings
from typing import Any

import gymnasium
import numpy as np

from jackdaw_arena.client import ArenaClient


class ArenaEnv(gymnasium.Env):
    metadata: dict[str, Any] = {"render_modes": []}

    def __init__(
        self,
        client: ArenaClient | None = None,
        track: str = "red-1",
        reward: str = "sparse",
        weights: dict[str, float] | None = None,
    ) -> None:
        super().__init__()
        self.client = client or ArenaClient()
        self.track, self.reward, self.weights = track, reward, weights
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
        (ep,) = self.client.create(1, self.track, self.reward, self.weights)
        self.episode_id = ep["id"]
        self._t, self._n_actions, self._running = ep["t"], ep["n_actions"], True
        return self.spec.decode(ep["obs"]), {
            "action_mask": self.action_masks(),
            "arena/episode_id": self.episode_id,
        }

    def step(self, action: int) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        if not self._running or self.episode_id is None:
            raise RuntimeError("call reset() first: the episode has ended")
        (r,) = self.client.step([(self.episode_id, self._t, int(action))])
        if not r["ok"]:
            raise RuntimeError(f"step refused: {r['error']} (t={r.get('t')})")
        self._t, self._n_actions = r["t"], r["n_actions"]
        info: dict[str, Any] = {"action_mask": None, "arena/episode_id": self.episode_id}
        final = r["final"]
        if final is not None:
            self._running = False
            self._n_actions = 0
            info.update(final_info(final))
        info["action_mask"] = self.action_masks()
        return self.spec.decode(r["obs"]), r["reward"], r["terminated"], r["truncated"], info

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
