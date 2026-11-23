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

An agent that plans can read the run as a player sees it and give its actions directly, as with jackdaw's `BalatroGymnasiumEnv`: `player_view()` returns jackdaw's player view (no hidden information), and `step_factored()` takes any action the env offers, including the plays a sampled action table leaves out.

```python
env = ArenaEnv(view=True)
obs, info = env.reset()
view = env.player_view()
obs, reward, terminated, truncated, info = env.step_factored((0, None, (0, 2, 3, 5, 7)))  # PlayHand
```

An agent that searches or simulates needs a game to plan on. With jackdaw installed (0.3.2 or later), `view_game()` builds one from the view: a jackdaw `Game` whose every field a player sees is the view's, and whose hidden parts (the draw pile's order, face-down cards, the RNG) are stand-ins. It's kept across the episode with the actions taken, so it also knows what they taught and no view lists, such as the consumables used and the cards played this ante. jackdaw's `BalatroGymnasiumEnv.view_game()` builds the same game from the same view, so the agent plans with the same code locally. Take factored steps: an index leaves no action to step the game with, as the action table is the server's.

```python
env = ArenaEnv(view=True)
obs, info = env.reset()
game = env.view_game()               # a jackdaw Game: step it, preview plays, roll out
obs, reward, terminated, truncated, info = env.step_factored(plan(game))
```

`evaluate(choose, ..., view=True)` hands each episode's view to the chooser (`envs[i].view`, and `envs[i].view_game()`), and the chooser may return factored actions as well as indices.

Every episode an agent starts counts, and each agent has a fixed budget per track (500 on `red-1`). Every result is verified on the server by replay, and once an episode ends, its seed and full tape are public:

```bash
jackdaw-arena tape <episode-id> -o tape.json
jackdaw-arena verify tape.json      # needs jackdaw installed
```

`verify` replays the tape with the jackdaw you have installed and compares the final state hash with the published one. Any release that reproduces it verifies the episode; one that doesn't may have changed the rules, so `verify` then names the release the tape was recorded with, which settles it.
