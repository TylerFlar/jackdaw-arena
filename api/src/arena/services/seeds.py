"""Where episode seeds come from.

An arena seed must be impossible to guess from what an agent sees, because a known seed means
known deck order and draws. Vanilla's 8-character seeds (``jackdaw.core.game.random_seed``)
carry about 40 bits with a skewed alphabet: enough to brute-force from the first boss, tags
and hand. Arena seeds are 16 characters drawn uniformly from the same 34-symbol alphabet
(about 81 bits). The engine hashes any string.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable, Iterator

ALPHABET = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"  # vanilla's: no 0, no O
SEED_LENGTH = 16

SeedSource = Callable[[], tuple[str, int]]
"""``() -> (seed, rng_seed)``: a run seed and the action-table sampler's seed."""


def secure_seeds() -> tuple[str, int]:
    seed = "".join(secrets.choice(ALPHABET) for _ in range(SEED_LENGTH))
    # Postgres bigint is signed; the sampler takes any u64, so 63 bits keeps both happy.
    return seed, secrets.randbits(63)


class FixedSeeds:
    """Seeds from a list, for tests: ``FixedSeeds([("12345", 12345), ...])``."""

    def __init__(self, seeds: Iterable[tuple[str, int]]) -> None:
        self._it: Iterator[tuple[str, int]] = iter(seeds)

    def __call__(self) -> tuple[str, int]:
        return next(self._it)
