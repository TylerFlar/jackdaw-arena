"""A jackdaw ``Game`` built from an episode's player view, kept across the episode.

An agent that plans with the engine (a search, rollouts, score previews) needs a game to plan
on, and the Arena gives it only the player's view. jackdaw (0.3.2 and later) builds one from
the view: every field a player sees is the view's, the hidden parts are stand-ins, and a
``ViewTracker`` keeps it across the episode with the actions the agent took, so it knows what
those actions taught and no view lists. It's the game ``BalatroGymnasiumEnv.view_game()``
gives locally. The client itself doesn't depend on jackdaw; this needs it installed.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jackdaw_arena.spec import Spec

JACKDAW = "uv add git+https://github.com/TylerFlar/jackdaw-balatro.git --branch main"


class ViewGame:
    """One episode's game from its views: :meth:`game` before an action, :meth:`stepped`
    after it. Given the Arena's ``spec``, it warns when the installed jackdaw's action space
    isn't the Arena's."""

    def __init__(self, spec: Spec | None = None) -> None:
        try:
            from jackdaw.core import ViewTracker
        except ImportError:
            raise ImportError(
                "view_game() needs jackdaw 0.3.2 or later (Python 3.12+), which builds the "
                f"game from the view: {JACKDAW}"
            ) from None
        if spec is not None:
            _check_action_space(spec)
        self._tracker = ViewTracker()
        self._game: Any = None

    def reset(self) -> None:
        self._tracker.reset()
        self._game = None

    def game(self, view: Mapping[str, Any]) -> Any:
        """The game for ``view``, the episode's view now (a copy, to step as you like)."""
        if self._game is None:
            self._game = self._tracker.update(view)
        return self._game.clone()

    def before_step(self, view: Mapping[str, Any] | None) -> None:
        """Before a step: the game for the state it leaves, if :meth:`game` didn't build it."""
        if self._game is None and view is not None:
            self._game = self._tracker.update(view)

    def stepped(self, action: int | Mapping[str, Any]) -> None:
        """After a step with ``action`` as the protocol took it: a factored action steps the
        game; an index leaves no action to step it with (the table is the server's), and the
        next game builds on this one as it is."""
        if isinstance(action, Mapping):
            self._tracker.step(action)
        self._game = None


def _check_action_space(spec: Spec) -> None:
    """Warn when the installed jackdaw's action space (``ACTION_VERSION``) isn't the Arena's:
    an agent that plans with it may choose actions the Arena doesn't offer, or miss ones it
    does. jackdaw 0.4 (action space 3), for one, has Aura name its card."""
    try:
        from jackdaw import _core
    except ImportError:
        return
    ours = getattr(_core, "ACTION_VERSION", None)
    if ours is None or ours == spec.action_version:
        return
    release = spec.engine_version
    warnings.warn(
        f"the installed jackdaw ({getattr(_core, '__version__', '?')}) has action space "
        f"{ours}, the Arena's (jackdaw {release}) {spec.action_version}: plan with the Arena's "
        "release, or the actions you choose may not be the ones it offers. "
        f"uv add git+https://github.com/TylerFlar/jackdaw-balatro.git --tag v{release}",
        stacklevel=4,
    )
