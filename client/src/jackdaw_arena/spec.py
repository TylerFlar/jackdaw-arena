"""The server's ``/api/v1/spec``: observation layout, action space, tracks. Spaces built from it
equal ``jackdaw.env.BalatroGymnasiumEnv``'s, so a policy trained locally plugs straight in."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import numpy as np
from gymnasium import spaces


@dataclass(frozen=True)
class Spec:
    raw: dict[str, Any]

    @property
    def engine_version(self) -> str:
        return self.raw["engine_version"]

    @property
    def action_version(self) -> int:
        return int(self.raw["action_version"])

    @property
    def max_actions(self) -> int:
        return int(self.raw["max_actions"])

    @property
    def fields(self) -> list[dict[str, Any]]:
        return self.raw["obs"]["fields"]

    @property
    def obs_length(self) -> int:
        return int(self.raw["obs"]["length"])

    def tracks(self) -> dict[str, dict[str, Any]]:
        return {t["key"]: t for t in self.raw["tracks"]}

    def decode(self, b64: str) -> dict[str, np.ndarray]:
        """One observation: base64 of little-endian float32 values, split into the named arrays
        ``BalatroGymnasiumEnv`` returns."""
        flat = np.frombuffer(base64.b64decode(b64), dtype=self.raw["obs"]["dtype"])
        if flat.size != self.obs_length:
            raise ValueError(f"expected {self.obs_length} values, got {flat.size}")
        flat = flat.astype(np.float32)  # native order, and a writable copy
        out: dict[str, np.ndarray] = {}
        for f in self.fields:
            size = int(np.prod(f["shape"]))
            out[f["name"]] = flat[f["offset"] : f["offset"] + size].reshape(f["shape"])
        return out

    def mask(self, n_actions: int) -> np.ndarray:
        m = np.zeros(self.max_actions, dtype=bool)
        m[:n_actions] = True
        return m

    def observation_space(self) -> spaces.Dict:
        entity_max = [f["shape"][0] for f in self.fields if len(f["shape"]) == 2]
        out: dict[str, spaces.Space] = {}
        for f in self.fields:
            if f["name"] == "entity_counts":
                out[f["name"]] = spaces.Box(
                    low=0, high=np.array(entity_max, dtype=np.float32), shape=tuple(f["shape"]),
                    dtype=np.float32,
                )  # fmt: skip
            else:
                out[f["name"]] = spaces.Box(
                    -np.inf, np.inf, shape=tuple(f["shape"]), dtype=np.float32
                )
        return spaces.Dict(out)

    def action_space(self) -> spaces.Discrete:
        return spaces.Discrete(self.max_actions)
