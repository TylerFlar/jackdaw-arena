"""Evaluate Balatro agents on Jackdaw Arena.

from jackdaw_arena import ArenaEnv, evaluate

env = ArenaEnv()                      # a drop-in for jackdaw's BalatroGymnasiumEnv
result = evaluate(choose, episodes=500)
print(result.summary())
"""

from jackdaw_arena.client import ArenaClient, ArenaError, find_token
from jackdaw_arena.env import ArenaEnv
from jackdaw_arena.evaluate import EpisodeResult, Evaluation, evaluate, random_chooser
from jackdaw_arena.spec import Spec

__version__ = "0.1.0"

__all__ = [
    "ArenaClient",
    "ArenaEnv",
    "ArenaError",
    "EpisodeResult",
    "Evaluation",
    "Spec",
    "evaluate",
    "find_token",
    "random_chooser",
]
