"""A running episode, and how to rebuild one from what the database keeps.

The database stores a run's spec (seed, sampler seed, track settings) and the index of every
action the agent took. That is enough to rebuild the Gym env exactly. ``_core.GymEnv`` is
deterministic given its spec and ``rng_seed``, including the per-step action table it samples.

Next to the env runs a *shadow* ``Game``, stepped with each action's canonical engine form. Those
JSON "tape" lines are what the episode records, and anyone can replay them with
``Game.new(back, stake, seed)``. When the episode ends, the shadow must sit on exactly the env's
state (``state_hash``); that check is the ``verified`` flag.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from jackdaw import _core

# Exceptions that must never be swallowed. Everything else raised by the engine (including
# PyO3's PanicException, a BaseException) ends the episode as an engine error.
_NEVER_CATCH = (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)


class CorruptTrace(RuntimeError):
    """The stored indices don't replay: wrong spec, a different engine, or a damaged row."""


@dataclass(frozen=True)
class RunSpec:
    """Everything that determines an episode, as stored with it."""

    back: str
    stake: int
    seed: str
    rng_seed: int
    max_steps: int
    end_on_win: bool = True
    max_free_moves: int | None = 10
    reward_kind: str = "sparse"
    reward_weights: tuple[float, ...] | None = None
    challenge: str | None = None


EnvFactory = Callable[[RunSpec, int], Any]
"""``factory(spec, max_steps)``: a ``_core.GymEnv`` for the spec, capped at ``max_steps``."""


def gym_env(spec: RunSpec, max_steps: int) -> Any:
    return _core.GymEnv(
        spec.back, spec.stake, spec.seed, spec.challenge, spec.rng_seed, max_steps,
        spec.end_on_win, spec.reward_kind, spec.reward_weights, spec.max_free_moves,
    )  # fmt: skip


def new_game(spec: RunSpec) -> Any:
    return _core.Game.new(spec.back, spec.stake, spec.seed, spec.challenge)


@dataclass(frozen=True)
class Outcome:
    """How an episode ended. ``length`` counts every action the agent took, including one the
    engine refused or couldn't play (which ends the episode)."""

    end_reason: str  # won | lost | max_steps | refused | not_ported | engine_error | forfeit | idle
    won: bool
    ante_reached: int
    rounds_beaten: int
    length: int
    final_state_hash: str
    verified: bool
    refused: str | None = None
    not_ported: str | None = None
    attempted: Any = None  # the action the run couldn't take: tape form, else factored parts


@dataclass(frozen=True)
class StepResult:
    t: int
    obs: bytes
    n_actions: int
    reward: float
    terminated: bool
    truncated: bool
    outcome: Outcome | None = None


@dataclass(frozen=True)
class Stats:
    ante_reached: int
    rounds_beaten: int
    won: bool
    state_hash: str


@dataclass
class LiveEpisode:
    """The env an agent steps plus the shadow run recording its tape. Not thread-safe."""

    spec: RunSpec
    env: Any
    shadow: Any
    obs: bytes
    n_actions: int
    factory: EnvFactory = gym_env
    t: int = 0
    indices: list[int] = field(default_factory=list)
    tape: list[str] = field(default_factory=list)  # JSON text, one engine action per line
    last: tuple[int, StepResult] | None = None  # the last action and its result, for retries
    outcome: Outcome | None = None
    diverged: bool = False  # the shadow refused an action the env took: an engine bug
    engine_error: str | None = None  # what the engine raised, kept for operators only

    @classmethod
    def start(cls, spec: RunSpec, factory: EnvFactory = gym_env) -> LiveEpisode:
        env = factory(spec, spec.max_steps)
        obs, n_actions = env.reset(spec.back, spec.stake, spec.seed, spec.challenge, spec.rng_seed)
        return cls(spec, env, new_game(spec), bytes(obs), n_actions, factory)

    @classmethod
    def rebuild(
        cls, spec: RunSpec, indices: Sequence[int], factory: EnvFactory = gym_env
    ) -> LiveEpisode:
        """The episode after replaying ``indices``. The last replayed step's result is ``last``,
        so a retried request gets the response it lost, from any process."""
        live = cls.start(spec, factory)
        for a in indices:
            if live.outcome is not None:
                raise CorruptTrace(f"steps recorded after the episode ended (t={live.t})")
            if not 0 <= a < live.n_actions:
                raise CorruptTrace(f"index {a} at t={live.t} is outside the table")
            live.apply(a)
        return live

    def apply(self, a: int) -> StepResult:
        """Take action ``a`` of the current table. The caller checks ``0 <= a < n_actions`` and
        that the episode is still running."""
        if self.outcome is not None:
            raise RuntimeError("the episode has ended")
        parts = self.env.action(a)  # (action_type, entity_target, card_target)
        try:
            tape: str | None = self.shadow.factored_to_engine(*parts)
        except ValueError:
            tape = None  # no engine action stands for it here: the env will refuse it
        try:
            obs, reward, term, trunc, n_actions, episode, not_ported, refused = self.env.step(
                a, True
            )
        except _NEVER_CATCH:
            raise
        except BaseException as exc:  # noqa: BLE001 - includes PyO3 PanicException
            return self._engine_error(a, parts, tape, exc)

        self.indices.append(a)
        self.t += 1
        took = refused is None and not_ported is None
        if took:
            if tape is None:  # pragma: no cover - the env took an action with no engine form
                self.diverged = True
            elif not self.diverged:
                try:
                    self.shadow.step(tape)
                    self.tape.append(tape)
                except _NEVER_CATCH:
                    raise
                except BaseException:  # noqa: BLE001
                    self.diverged = True

        outcome = None
        if term or trunc:
            outcome = self._finish(episode, term, refused, not_ported, tape, parts)
        result = StepResult(
            self.t, bytes(obs), int(n_actions), float(reward), bool(term), bool(trunc), outcome
        )
        self.obs, self.n_actions = result.obs, result.n_actions
        self.last = (a, result)
        self.outcome = outcome
        return result

    def end(self, reason: str) -> Outcome:
        """End a running episode the agent didn't finish (``forfeit``/``idle``), scored by a clean
        replay of its steps."""
        if self.outcome is not None:
            return self.outcome
        stats = replay_stats(self.spec, self.indices, self.factory)
        shadow_hash = self.shadow.state_hash()
        self.outcome = Outcome(
            reason, stats.won, stats.ante_reached, stats.rounds_beaten, self.t, shadow_hash,
            verified=not self.diverged and stats.state_hash == shadow_hash,
        )  # fmt: skip
        return self.outcome

    # ------------------------------------------------------------------

    def _finish(
        self,
        episode: tuple[Any, int, bool] | None,
        terminated: bool,
        refused: str | None,
        not_ported: str | None,
        tape: str | None,
        parts: Any,
    ) -> Outcome:
        if episode is None:  # pragma: no cover - the env always reports stats at an end
            raise RuntimeError("the env ended an episode without its stats")
        ante, rounds, won = episode
        if refused is not None:
            reason = "refused"
        elif not_ported is not None:
            reason = "not_ported"
        elif terminated:
            reason = "won" if won else "lost"
        else:
            reason = "max_steps"
        shadow_hash = self.shadow.state_hash()
        if self.diverged:
            verified = False
        elif not_ported is not None:
            # A not-ported step leaves the env mid-step (no rollback), so its state can't be
            # compared. The record holds if the shadow, at the state before, can't take it either.
            verified = tape is not None and _raises_not_ported(self.shadow, tape)
        else:
            # A refused action leaves the env's run unchanged, so the states must agree.
            verified = shadow_hash == self.env.game().state_hash()
        attempted = None
        if refused is not None or not_ported is not None:
            attempted = json.loads(tape) if tape is not None else list(parts)
        return Outcome(
            reason, bool(won), int(ante), int(rounds), self.t, shadow_hash, verified,
            refused=refused, not_ported=not_ported, attempted=attempted,
        )  # fmt: skip

    def _engine_error(self, a: int, parts: Any, tape: str | None, exc: BaseException) -> StepResult:
        """The engine raised on a step: the env is in an undefined state. Record the step, end the
        episode, and score it from a clean replay of the steps before."""
        stats = replay_stats(self.spec, self.indices, self.factory)
        shadow_hash = self.shadow.state_hash()
        self.indices.append(a)
        self.t += 1
        self.outcome = Outcome(
            "engine_error", stats.won, stats.ante_reached, stats.rounds_beaten, self.t,
            shadow_hash, verified=not self.diverged and stats.state_hash == shadow_hash,
            attempted=json.loads(tape) if tape is not None else list(parts),
        )  # fmt: skip
        self.engine_error = f"{type(exc).__name__}: {exc}"[:500]
        result = StepResult(self.t, self.obs, 0, 0.0, False, True, self.outcome)
        self.n_actions, self.last = 0, (a, result)
        return result


def replay_stats(spec: RunSpec, indices: Sequence[int], factory: EnvFactory = gym_env) -> Stats:
    """The authoritative stats of an episode stopped after ``indices``.

    ``_core.GymEnv`` only reports an episode's best ante and blinds beaten when it ends, so
    replay the indices in a fresh env capped at ``len(indices)`` steps: its last step truncates
    and reports them.
    """
    t = len(indices)
    if t == 0:
        return Stats(1, 0, False, new_game(spec).state_hash())
    env = factory(spec, t)
    env.reset(spec.back, spec.stake, spec.seed, spec.challenge, spec.rng_seed)
    episode = None
    for k, a in enumerate(indices):
        _, _, term, trunc, _, episode, _, _ = env.step(a, True)
        if (term or trunc) != (k == t - 1):
            raise CorruptTrace(f"replay ended at step {k + 1}, not at {t}")
    assert episode is not None
    ante, rounds, won = episode
    return Stats(int(ante), int(rounds), bool(won), env.game().state_hash())


def verify_tape(spec: RunSpec, tape: Sequence[str]) -> str:
    """Replay a tape on a fresh run and return its final ``state_hash``. Raises if a line can't
    be played. What anyone holding the revealed seed can run with jackdaw alone."""
    game = new_game(spec)
    for line in tape:
        game.step(line)
    return game.state_hash()


def _raises_not_ported(shadow: Any, tape: str) -> bool:
    probe = shadow.clone()
    try:
        probe.step(tape)
    except _core.NotPortedError:
        return True
    except Exception:  # noqa: BLE001 - any other outcome means the records disagree
        return False
    return False
