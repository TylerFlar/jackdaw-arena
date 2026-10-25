# Jackdaw Arena

A leaderboard for agents that play Balatro, run on the [jackdaw](https://github.com/TylerFlar/jackdaw-balatro) simulator: **https://arena.tylerflar.com**

## Evaluate an agent

1. Sign in on the site with GitHub, create an agent, and create a token for it. Save the token as `ARENA_TOKEN` or in `~/.jackdaw-arena/token`.
2. Install the client:

   ```bash
   uv add "jackdaw-arena @ git+https://github.com/TylerFlar/jackdaw-arena@main#subdirectory=client"
   ```

3. Play. `ArenaEnv` works like jackdaw's `BalatroGymnasiumEnv`, with the same observations, actions and `action_masks()`:

   ```python
   from jackdaw_arena import ArenaEnv

   env = ArenaEnv()
   obs, info = env.reset()
   done = False
   while not done:
       action = model.predict(obs, action_masks=env.action_masks())[0]
       obs, reward, terminated, truncated, info = env.step(int(action))
       done = terminated or truncated
   ```

   To play your agent's whole budget in batches, use `evaluate()`. It takes the chooser from jackdaw's `examples/balatro_sb3.py`, and picks up where it stopped if interrupted:

   ```python
   from sb3_contrib import MaskablePPO
   from jackdaw_arena import evaluate

   model = MaskablePPO.load("maskable_ppo_balatro.zip")

   def choose(envs, obs, masks):
       actions, _ = model.predict(obs, action_masks=masks, deterministic=True)
       return actions

   print(evaluate(choose, episodes=500, batch=32).summary())
   ```

4. Your agent shows up on the leaderboard, and every run can be replayed from its page.

## Rules

- Each agent plays 500 runs on a track, and is ranked once all of them have ended.
- Every run counts, including ones you abandon.
- The score is the average number of blinds beaten per run.

[Get started](https://arena.tylerflar.com/docs) on the site has the details. The API is documented at [/api/docs](https://arena.tylerflar.com/api/docs).

To check a finished run yourself, install jackdaw and run `jackdaw-arena verify <episode-id>`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, for the code in this repository. Jackdaw Arena isn't affiliated with LocalThunk or Playstack; Balatro and its art are theirs.
