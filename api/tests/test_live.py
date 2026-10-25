"""The episode engine against jackdaw itself: no database, no HTTP."""

from __future__ import annotations

import contextlib
import json
from dataclasses import replace

import numpy as np
import pytest
from jackdaw.env import BalatroGymnasiumEnv, DirectAdapter
from jackdaw.env.rewards import ShapedReward, blind_progress_reward, sparse_reward

from arena.engine.live import (
    CorruptTrace,
    LiveEpisode,
    RunSpec,
    gym_env,
    replay_stats,
    verify_tape,
)
from arena.engine.spec import OBS_LEN, reward_weights
from arena.services.seeds import ALPHABET, SEED_LENGTH, secure_seeds


def spec_for(seed: str, rng_seed: int, **kw) -> RunSpec:
    defaults = dict(back="b_red", stake=1, max_steps=2000, end_on_win=True, max_free_moves=10)
    return RunSpec(seed=seed, rng_seed=rng_seed, **{**defaults, **kw})


def test_spec(i: int, **kw) -> RunSpec:
    """A deterministic 16-character seed per ``i``."""
    return spec_for(f"ARENATEST{i:07d}", 1_000 + i, **kw)


test_spec.__test__ = False  # a helper, not a test


def play_random(live: LiveEpisode, rng: np.random.Generator) -> list[int]:
    while live.outcome is None:
        live.apply(int(rng.integers(live.n_actions)))
    return live.indices


def flat(obs: dict[str, np.ndarray]) -> bytes:
    return np.concatenate([obs[k].ravel() for k in obs]).tobytes()


@pytest.mark.parametrize(
    ("kind", "reward_fn"),
    [("sparse", sparse_reward), ("blind_progress", blind_progress_reward), ("shaped", None)],
)
@pytest.mark.parametrize("max_steps", [2000, 25])
def test_matches_local_gymnasium_env(kind, reward_fn, max_steps):
    """An arena episode with seed str(N) and sampler seed N is BalatroGymnasiumEnv's
    reset(seed=N), step for step: obs bytes, mask, reward, flags and end info."""
    fn = ShapedReward() if kind == "shaped" else reward_fn
    for n in (7, 1234, 99_000_001):
        local = BalatroGymnasiumEnv(
            adapter_factory=DirectAdapter, reward_fn=fn, max_steps=max_steps
        )
        spec = spec_for(
            str(n), n, max_steps=max_steps, reward_kind=kind,
            reward_weights=reward_weights(kind, None),
        )  # fmt: skip
        live = LiveEpisode.start(spec)
        obs, _ = local.reset(seed=n)
        assert live.obs == flat(obs)
        rng = np.random.default_rng(n)
        done = False
        while not done:
            mask = local.action_masks()
            assert int(mask.sum()) == live.n_actions and mask[: live.n_actions].all()
            a = int(rng.integers(live.n_actions))
            obs, reward, term, trunc, info = local.step(a)
            r = live.apply(a)
            assert (r.obs, r.reward, r.terminated, r.truncated) == (flat(obs), reward, term, trunc)
            done = term or trunc
        out = live.outcome
        assert out is not None and out.verified
        assert out.ante_reached == info["balatro/ante_reached"]
        assert out.rounds_beaten == info["balatro/rounds_beaten"]
        assert out.won == info["balatro/won"]
        if out.length == max_steps:
            assert out.end_reason == "max_steps"


def test_obs_is_one_flat_buffer():
    live = LiveEpisode.start(test_spec(0))
    assert len(live.obs) == OBS_LEN * 4


def test_rebuild_equals_uninterrupted():
    """Replaying stored indices gives the same state, table and last response at every t."""
    rng = np.random.default_rng(3)
    for i in range(6):
        spec = test_spec(i)
        live = LiveEpisode.start(spec)
        while live.outcome is None:
            live.apply(int(rng.integers(live.n_actions)))
            again = LiveEpisode.rebuild(spec, live.indices)
            assert (again.t, again.obs, again.n_actions) == (live.t, live.obs, live.n_actions)
            assert again.last == live.last
            assert again.tape == live.tape
        assert live.outcome.verified


def test_tape_replays_to_the_final_hash_and_detects_tampering():
    spec = test_spec(11)
    live = LiveEpisode.start(spec)
    play_random(live, np.random.default_rng(11))
    assert live.outcome is not None and live.outcome.verified
    assert verify_tape(spec, live.tape) == live.outcome.final_state_hash
    # Another seed, or a dropped line, can't reach the same state.
    for spec_, tape in ((test_spec(12), live.tape), (spec, live.tape[:-1])):
        # A tape that stops being legal (ValueError) is also a detection.
        with contextlib.suppress(ValueError):
            assert verify_tape(spec_, tape) != live.outcome.final_state_hash


def test_rebuild_rejects_a_trace_past_the_end():
    spec = test_spec(5)
    live = LiveEpisode.start(spec)
    play_random(live, np.random.default_rng(5))
    with pytest.raises(CorruptTrace):
        LiveEpisode.rebuild(spec, [*live.indices, 0])


def test_replay_stats_match_a_natural_truncation():
    """Stats of an episode stopped at t equal those the env reports when its cap is t."""
    rng = np.random.default_rng(8)
    for i in range(5):
        spec = test_spec(20 + i)
        full = play_random(LiveEpisode.start(spec), rng)
        assert (replay_stats(spec, []).ante_reached, replay_stats(spec, []).won) == (1, False)
        for t in sorted({1, len(full) // 2, len(full) - 1} - {0}):
            stats = replay_stats(spec, full[:t])
            cut = LiveEpisode.rebuild(replace(spec, max_steps=t), full[:t]).outcome
            assert cut is not None and cut.end_reason == "max_steps" and cut.length == t
            assert (stats.ante_reached, stats.rounds_beaten, stats.won) == (
                cut.ante_reached,
                cut.rounds_beaten,
                cut.won,
            )
            assert stats.state_hash == cut.final_state_hash


def test_forfeit_scores_partial_progress_and_verifies():
    spec = test_spec(31)
    live = LiveEpisode.start(spec)
    rng = np.random.default_rng(31)
    for _ in range(4):
        if live.outcome is None:
            live.apply(int(rng.integers(live.n_actions)))
    assert live.outcome is None, "pick a seed whose random run lasts over 4 steps"
    out = live.end("forfeit")
    assert out.end_reason == "forfeit" and out.verified and out.length == 4
    assert live.end("idle") is out  # ending twice keeps the first outcome


def test_secure_seeds_are_long_and_from_the_alphabet():
    seen = set()
    for _ in range(200):
        seed, rng_seed = secure_seeds()
        assert len(seed) == SEED_LENGTH and set(seed) <= set(ALPHABET)
        assert 0 <= rng_seed < 2**63
        seen.add(seed)
    assert len(seen) == 200


# --- engine failures, through a fake env -------------------------------------------------------


class Panic(BaseException):
    """Stands in for pyo3_runtime.PanicException, which derives from BaseException."""


class FlakyEnv:
    """A real GymEnv that misbehaves at its ``at``-th step."""

    def __init__(self, inner, at: int, mode: str) -> None:
        self.inner, self.at, self.mode, self.k = inner, at, mode, 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def step(self, a, cut):
        self.k += 1
        if self.k != self.at:
            return self.inner.step(a, cut)
        if self.mode == "panic":
            raise Panic("engine panicked")
        out = list(self.inner.step(a, cut))
        out[2], out[3], out[5] = False, True, (1, 0, False)  # cut the episode
        out[7 if self.mode == "refused" else 6] = f"fake {self.mode}"
        return tuple(out)


def flaky(at: int, mode: str):
    def factory(spec, max_steps):
        env = gym_env(spec, max_steps)
        # Only the live env misbehaves; replays for stats get a clean one.
        return FlakyEnv(env, at, mode) if max_steps == spec.max_steps else env

    return factory


def test_engine_panic_ends_the_episode_with_replayed_stats():
    rng = np.random.default_rng(2)
    live = LiveEpisode.start(test_spec(40), flaky(3, "panic"))
    results = [live.apply(int(rng.integers(live.n_actions))) for _ in range(3)]
    out = results[-1].outcome
    assert out is not None and out.end_reason == "engine_error"
    assert results[-1].truncated and out.length == 3 and live.t == 3
    assert out.verified  # the record of the two steps before is intact
    assert out.attempted is not None
    assert live.engine_error and "panicked" in live.engine_error
    assert len(live.tape) == 2


def test_fake_not_ported_cut_is_not_verified():
    """The env claims it can't play the step but the shadow can: the records disagree."""
    rng = np.random.default_rng(4)
    live = LiveEpisode.start(test_spec(41), flaky(2, "not_ported"))
    live.apply(int(rng.integers(live.n_actions)))
    out = live.apply(int(rng.integers(live.n_actions))).outcome
    assert out is not None and out.end_reason == "not_ported" and not out.verified
    assert out.not_ported == "fake not_ported" and out.attempted is not None
    assert len(live.tape) == 1  # the cut action isn't on the tape


def test_refused_cut_records_the_attempt_off_the_tape():
    rng = np.random.default_rng(6)
    live = LiveEpisode.start(test_spec(42), flaky(2, "refused"))
    live.apply(int(rng.integers(live.n_actions)))
    out = live.apply(int(rng.integers(live.n_actions))).outcome
    assert out is not None and out.end_reason == "refused"
    assert out.refused == "fake refused" and json.dumps(out.attempted)
    assert len(live.tape) == 1
