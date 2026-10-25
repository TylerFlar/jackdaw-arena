# jackdaw-arena

The client for [Jackdaw Arena](https://arena.tylerflar.com): evaluate a Balatro agent on server-held seeds.

```bash
uv add "jackdaw-arena @ git+https://github.com/TylerFlar/jackdaw-arena@main#subdirectory=client"
```

Create an agent and a token on your Arena account page, then make the token available as `ARENA_TOKEN` or save it to `~/.jackdaw-arena/token`.

```python
from jackdaw_arena import ArenaEnv, evaluate

# A drop-in for jackdaw's BalatroGymnasiumEnv: same observations, Discrete(500), action_masks().
env = ArenaEnv()
obs, info = env.reset()

# Or evaluate a batch policy with the chooser signature from jackdaw's examples/balatro_sb3.py:
result = evaluate(model_chooser(model), episodes=500)
print(result.summary())
```

Every episode an agent starts counts, and each agent has a fixed budget per track (500 on `red-1`). Every result is verified on the server by replay, and once an episode ends, its seed and full tape are public:

```bash
jackdaw-arena tape <episode-id> -o tape.json
jackdaw-arena verify tape.json      # needs jackdaw installed
```

`verify` replays the tape with the jackdaw you have installed and compares the final state hash with the published one. Any release that reproduces it verifies the episode; one that doesn't may have changed the rules, so `verify` then names the release the tape was recorded with, which settles it.
