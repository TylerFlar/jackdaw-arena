"""A running episode, and how to rebuild one from what the database keeps.

The database stores a run's spec (seed, sampler seed, track settings) and every action the agent
took: an index into the step's action table, or a factored action the env offers (one the table
would hold if it held every legal action instead of a sample). That is enough to rebuild the Gym
env exactly. ``_core.GymEnv`` is deterministic given its spec and ``rng_seed``, including the
per-step action table it samples, and a factored step draws the next table as the index naming
the same action would.

Next to the env runs a *shadow* ``Game``, stepped with each action's canonical engine form. Those
JSON "tape" lines are what the episode records, and anyone can replay them with
``Game.new(back, stake, seed)``. When the episode ends, the shadow must sit on exactly the env's
state (``state_hash``); that check is the ``verified`` flag.

Indices are what make a rebuild depend on the release: another jackdaw may list the same state's
actions in another table, and read an old index as another action. So each step also records
the ``digest`` of what the agent saw after it, which another release must rebuild to before it
continues the episode.
"""

from __future__ import annotations

import array
import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from jackdaw import _core

# Exceptions that must never be swallowed. Everything else raised by the engine (including
# PyO3's PanicException, a BaseException) ends the episode as an engine error.
NEVER_CATCH = (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)


class CorruptTrace(RuntimeError):
    """The stored steps don't replay: wrong spec, a different engine, or a damaged row."""


class Factored(NamedTuple):
    """An action of jackdaw's factored space (``FactoredAction``), as an agent may give it
    instead of an index: legal when the env ``offers`` it."""

    action_type: int
    entity_target: int | None = None
    card_target: tuple[int, ...] | None = None

    def parts(self) -> tuple[int, int | None, list[int] | None]:
        cards = None if self.card_target is None else list(self.card_target)
        return self.action_type, self.entity_target, cards

    def as_dict(self) -> dict[str, Any]:
        cards = None if self.card_target is None else list(self.card_target)
        return {
            "action_type": self.action_type,
            "entity_target": self.entity_target,
            "card_target": cards,
        }


Step = int | Factored
"""What an agent takes: an index into the action table, or a factored action."""


def env_step(env: Any, a: Step) -> Any:
    """Take ``a`` in a ``_core.GymEnv``, a refusal cutting the episode: ``step`` for an index,
    ``step_factored`` for a factored action."""
    if isinstance(a, Factored):
        return env.step_factored(*a.parts(), True)
    return env.step(a, True)


def step_json(a: Step) -> Any:
    """A step as the protocol writes it: the index, or the factored action's object."""
    return a.as_dict() if isinstance(a, Factored) else a


_DIGEST = b"jackdaw-arena/digest/1\0"


def view_digest(obs: bytes, table: Sequence[Sequence[Any]]) -> str:
    """What an agent sees at a step, hashed: the observation, and the action each index of the
    table names (``GymEnv.action_table()``). Two releases that rebuild a step to the same digest
    serve it alike, so the index the agent chooses next names the same action in both.

    The game's ``state_hash`` isn't part of it: it costs over ten times what the rest of a step
    does. Two rebuilds with one digest could only differ in what the observation leaves out, the
    hidden cards, and the agent's next action means the same in both."""
    words: list[int] = []
    for action_type, entity, cards in table:
        words.append(action_type)
        words.append(-1 if entity is None else entity)
        if cards is None:
            words.append(-1)
        else:
            words.append(len(cards))
            words.extend(cards)
    h = hashlib.sha256(_DIGEST)
    h.update(len(obs).to_bytes(4, "little"))
    h.update(obs)
    h.update(array.array("i", words).tobytes())  # int32 on every platform jackdaw builds for
    return h.hexdigest()


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
    steps: list[Step] = field(default_factory=list)
    tape: list[str] = field(default_factory=list)  # JSON text, one engine action per line
    last: tuple[Step, StepResult] | None = None  # the last action and its result, for retries
    outcome: Outcome | None = None
    diverged: bool = False  # the shadow refused an action the env took: an engine bug
    engine_error: str | None = None  # what the engine raised, kept for operators only

    @classmethod
    def start(cls, spec: RunSpec, factory: EnvFactory = gym_env) -> LiveEpisode:
        env = factory(spec, spec.max_steps)
        # Every play records its scoring, for the player view's ``last_play``. It never changes
        # a run.
        env.record_scoring = True
        obs, n_actions = env.reset(spec.back, spec.stake, spec.seed, spec.challenge, spec.rng_seed)
        return cls(spec, env, new_game(spec), bytes(obs), n_actions, factory)

    @classmethod
    def rebuild(
        cls, spec: RunSpec, steps: Sequence[Step], factory: EnvFactory = gym_env
    ) -> LiveEpisode:
        """The episode after replaying ``steps``. The last replayed step's result is ``last``,
        so a retried request gets the response it lost, from any process."""
        live = cls.start(spec, factory)
        for a in steps:
            if live.outcome is not None:
                raise CorruptTrace(f"steps recorded after the episode ended (t={live.t})")
            if not live.legal(a):
                raise CorruptTrace(f"step {a} at t={live.t} isn't legal there")
            live.apply(a)
        return live

    def legal(self, a: Step) -> bool:
        """Whether the episode takes ``a`` now: an index into the current table, or a factored
        action the env offers. Nothing is legal once it has ended."""
        if self.outcome is not None:
            return False
        if isinstance(a, Factored):
            return bool(self.env.offers(*a.parts()))
        return 0 <= a < self.n_actions

    def view(self) -> dict[str, Any]:
        """What a player sees of the run now (``jackdaw.player_view/1``), its cards named under
        a key drawn from the secret sampler seed."""
        return json.loads(self.env.player_view())

    def digest(self) -> str:
        """``view_digest`` of the step the agent is on: the observation and the action table it
        chooses from."""
        return view_digest(self.obs, self.env.action_table())

    def apply(self, a: Step) -> StepResult:
        """Take ``a``. The caller checks that it is ``legal``."""
        if self.outcome is not None:
            raise RuntimeError("the episode has ended")
        if isinstance(a, Factored):
            parts: Any = a.parts()
        else:
            parts = self.env.action(a)  # (action_type, entity_target, card_target)
        try:
            tape: str | None = self.shadow.factored_to_engine(*parts)
        except ValueError:
            tape = None  # no engine action stands for it here: the env will refuse it
        try:
            out = env_step(self.env, a)
            obs, reward, term, trunc, n_actions, episode, not_ported, refused = out
        except NEVER_CATCH:
            raise
        except BaseException as exc:  # noqa: BLE001 - includes PyO3 PanicException
            return self._engine_error(a, parts, tape, exc)

        self.steps.append(a)
        self.t += 1
        took = refused is None and not_ported is None
        if took:
            if tape is None:  # pragma: no cover - the env took an action with no engine form
                self.diverged = True
            elif not self.diverged:
                try:
                    self.shadow.step(tape)
                    self.tape.append(tape)
                except NEVER_CATCH:
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
        stats = replay_stats(self.spec, self.steps, self.factory)
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

    def _engine_error(
        self, a: Step, parts: Any, tape: str | None, exc: BaseException
    ) -> StepResult:
        """The engine raised on a step: the env is in an undefined state. Record the step, end the
        episode, and score it from a clean replay of the steps before."""
        stats = replay_stats(self.spec, self.steps, self.factory)
        shadow_hash = self.shadow.state_hash()
        self.steps.append(a)
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


def replay_stats(spec: RunSpec, steps: Sequence[Step], factory: EnvFactory = gym_env) -> Stats:
    """The authoritative stats of an episode stopped after ``steps``.

    ``_core.GymEnv`` only reports an episode's best ante and blinds beaten when it ends, so
    replay the steps in a fresh env capped at ``len(steps)`` steps: its last step truncates
    and reports them.
    """
    t = len(steps)
    if t == 0:
        return Stats(1, 0, False, new_game(spec).state_hash())
    env = factory(spec, t)
    env.reset(spec.back, spec.stake, spec.seed, spec.challenge, spec.rng_seed)
    episode = None
    for k, a in enumerate(steps):
        _, _, term, trunc, _, episode, _, _ = env_step(env, a)
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
