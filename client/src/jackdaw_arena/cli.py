"""``jackdaw-arena``: evaluate, inspect and verify from a shell.

    jackdaw-arena spec                          # engine, action space, tracks
    jackdaw-arena status                        # this agent's budget and running episodes
    jackdaw-arena eval --episodes 500           # a uniformly random policy
    jackdaw-arena eval --policy mypkg.agent:make_chooser --episodes 500
    jackdaw-arena tape EPISODE_ID -o tape.json  # an ended episode's full record
    jackdaw-arena verify tape.json              # replay it with jackdaw, check the hash
                                                # (exit 0 verified, 1 mismatch, 2 inconclusive)

The token comes from ``$ARENA_TOKEN`` or ``~/.jackdaw-arena/token``; the server from
``$ARENA_URL`` (default https://arena.tylerflar.com). Output is plain ASCII.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jackdaw_arena.client import ArenaClient, ArenaError
from jackdaw_arena.evaluate import evaluate, random_chooser


def load_chooser(target: str) -> Any:
    """``module:function``, where the function takes no arguments and returns a chooser."""
    module, _, name = target.partition(":")
    if not name:
        raise SystemExit(f"--policy expects module:function, not {target!r}")
    return getattr(importlib.import_module(module), name)()


def _install(version: str) -> str:
    return f"uv add git+https://github.com/TylerFlar/jackdaw-balatro.git --tag v{version}"


@dataclass(frozen=True)
class Verdict:
    """``verified``: the installed jackdaw replays the tape to the published final state.
    ``mismatch``: the tape's own jackdaw version doesn't, so the record is wrong.
    ``inconclusive``: another version doesn't, and its rules may differ from the tape's."""

    status: str
    message: str


def verify(tape: dict[str, Any]) -> Verdict:
    """Replay a tape on a fresh run with the installed jackdaw and compare the final state hash.

    A matching hash proves the result whichever jackdaw replayed it: a release that kept the
    rules (a documentation release, say) verifies older tapes too. Only the version the tape
    was recorded with can show a record wrong."""
    recorded = tape["engine_version"]
    try:
        from jackdaw import _core
        from jackdaw.core import Game
    except ImportError:
        raise SystemExit(f"verify needs jackdaw itself: {_install(recorded)}") from None
    installed = _core.__version__
    actions = len(tape["tape"])
    try:
        game = Game.new(tape["back"], int(tape["stake"]), tape["seed"])
        for action in tape["tape"]:
            game.step(action)
        same, why = game.state_hash() == tape["final_state_hash"], "a different final state"
    except Exception as exc:  # noqa: BLE001 - an action this engine won't play
        same, why = False, f"an action it won't play ({type(exc).__name__})"
    if same:
        note = "" if installed == recorded else f" with {installed}, recorded with {recorded}"
        return Verdict("verified", f"verified ({actions} actions{note})")
    if installed == recorded:
        return Verdict("mismatch", f"MISMATCH: jackdaw {installed} reaches {why}")
    return Verdict(
        "inconclusive",
        f"not reproduced: jackdaw {installed} reaches {why}, but the tape was recorded with "
        f"{recorded}, whose rules may differ. Check with that version: {_install(recorded)}",
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jackdaw-arena", description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", help="the Arena (default $ARENA_URL or arena.tylerflar.com)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("spec")
    sub.add_parser("status")
    ev = sub.add_parser("eval")
    ev.add_argument("--policy", default="random", help="'random' or module:function")
    ev.add_argument("--episodes", type=int, required=True)
    ev.add_argument("--track", default="red-1")
    ev.add_argument("--batch", type=int, default=32)
    ev.add_argument("--seed", type=int, default=0, help="seeds the random policy")
    ev.add_argument("--json", action="store_true", help="print the summary as JSON")
    tp = sub.add_parser("tape")
    tp.add_argument("episode")
    tp.add_argument("-o", "--out")
    vf = sub.add_parser("verify")
    vf.add_argument("target", help="a tape file, or an ended episode's id")
    args = parser.parse_args(argv)

    client = ArenaClient(url=args.url)
    try:
        if args.command == "spec":
            s = client.spec()
            print(f"engine {s.engine_version}, action space v{s.action_version}, "
                  f"Discrete({s.max_actions}), obs {s.obs_length} x float32")  # fmt: skip
            for key, t in s.tracks().items():
                print(f"  track {key}: {t['name']} ({t['episodes_per_agent']} episodes per agent)")
        elif args.command == "status":
            me = client.me()
            print(f"agent {me['agent']} ({me['name']}), season {me['season']}")
            print(f"  running: {me['running']}")
            for track, used in me["used"].items():
                print(f"  {track}: {used} episodes started")
        elif args.command == "eval":
            choose = (
                random_chooser(args.seed) if args.policy == "random" else load_chooser(args.policy)
            )
            result = evaluate(
                choose, args.episodes, track=args.track, batch=args.batch, client=client
            )
            s = result.summary()
            if args.json:
                print(json.dumps(s, indent=2))
            else:
                print(f"episodes {s['episodes']:.0f}: blinds beaten {s['blinds_beaten']:.3f} "
                      f"+- {s['blinds_beaten_sem']:.3f}, ante {s['ante_reached']:.2f}, "
                      f"wins {100 * s['win_rate']:.1f}%, length {s['length']:.1f}, "
                      f"all verified: {bool(s['verified'])}")  # fmt: skip
        elif args.command == "tape":
            doc = json.dumps(client.tape(args.episode), indent=1)
            if args.out:
                Path(args.out).write_text(doc + "\n", encoding="utf-8")
            else:
                print(doc)
        elif args.command == "verify":
            path = Path(args.target)
            tape = (
                json.loads(path.read_text(encoding="utf-8"))
                if path.exists()
                else client.tape(args.target)
            )
            verdict = verify(tape)
            print(f"{tape['id']}: {verdict.message}")
            sys.exit({"verified": 0, "mismatch": 1}.get(verdict.status, 2))
    except ArenaError as exc:
        raise SystemExit(f"error: {exc}") from None
    finally:
        client.close()


if __name__ == "__main__":
    main()
