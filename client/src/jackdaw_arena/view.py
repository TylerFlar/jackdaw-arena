"""A jackdaw ``Game`` built from an episode's player view, kept across the episode.

An agent that plans with the engine (a search, rollouts, score previews) needs a game to plan
on, and the Arena gives it only the player's view. jackdaw (0.3.2 and later) builds one from
the view: every field a player sees is the view's, the hidden parts are stand-ins, and a
``ViewTracker`` keeps it across the episode with the actions the agent took, so it knows what
those actions taught and no view lists. It's the game ``BalatroGymnasiumEnv.view_game()``
gives locally. The client itself doesn't depend on jackdaw; this needs it installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

JACKDAW = "uv add git+https://github.com/TylerFlar/jackdaw-balatro.git --branch main"


class ViewGame:
    """One episode's game from its views: :meth:`game` before an action, :meth:`stepped`
    after it."""

    def __init__(self) -> None:
        try:
            from jackdaw.core import ViewTracker
        except ImportError:
            raise ImportError(
                "view_game() needs jackdaw 0.3.2 or later (Python 3.12+), which builds the "
                f"game from the view: {JACKDAW}"
            ) from None
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
