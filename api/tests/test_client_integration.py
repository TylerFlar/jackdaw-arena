"""The real client (``client/``) against the real app: what a researcher's code would see."""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient
from jackdaw.env import BalatroGymnasiumEnv, DirectAdapter
from jackdaw.env.rewards import ShapedReward
from jackdaw_arena import ArenaClient, ArenaEnv, evaluate, random_chooser

from arena.services.seeds import FixedSeeds


def arena_client(app, token: str) -> ArenaClient:
    return ArenaClient(token, "http://testserver", http=TestClient(app))


def test_arena_env_is_balatro_gymnasium_env(make_app, agents):
    """ArenaEnv over HTTP, with the server's seed str(N) and sampler seed N, returns exactly what
    BalatroGymnasiumEnv(DirectAdapter).reset(seed=N) does: spaces, obs arrays, masks, rewards,
    flags and the final info keys."""
    seeds = [5, 808, 42_424]
    app = make_app(seeds=FixedSeeds((str(n), n) for n in seeds))
    _, token = agents.agent()
    with TestClient(app):
        env = ArenaEnv(arena_client(app, token), reward="shaped")
        local = BalatroGymnasiumEnv(adapter_factory=DirectAdapter, reward_fn=ShapedReward())
        assert env.observation_space == local.observation_space
        assert env.action_space == local.action_space
        assert env.action_version == local.action_version
        for n in seeds:
            obs, _ = env.reset()
            ref, _ = local.reset(seed=n)
            rng = np.random.default_rng(n)
            while True:
                assert set(obs) == set(ref) and all(np.array_equal(obs[k], ref[k]) for k in ref)
                assert np.array_equal(env.action_masks(), local.action_masks())
                a = int(rng.choice(np.flatnonzero(local.action_masks())))
                obs, r, term, trunc, info = env.step(a)
                ref, r_ref, term_ref, trunc_ref, info_ref = local.step(a)
                assert (r, term, trunc) == (r_ref, term_ref, trunc_ref)
                if term or trunc:
                    break
            for key in ("balatro/ante_reached", "balatro/rounds_beaten", "balatro/won"):
                assert info[key] == info_ref[key]
            assert info["arena/seed"] == str(n) and info["arena/final"]["verified"]


def test_evaluate_runs_an_exact_budget_on_the_server(app, agents):
    _, token = agents.agent()
    with TestClient(app):
        client = arena_client(app, token)
        result = evaluate(random_chooser(1), 10, batch=4, client=client, progress=False)
        s = result.summary()
        assert s["episodes"] == 10 and s["verified"] == 1.0
        assert client.me()["used"] == {"red-1": 10} and client.me()["running"] == 0
        tape = client.tape(result.results[0].id)
        assert tape["seed"] == result.results[0].seed
