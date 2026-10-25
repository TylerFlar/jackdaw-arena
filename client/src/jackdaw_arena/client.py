"""``ArenaClient``: the agent protocol over HTTP, with retries that are always safe.

Every call can be resent. A new episode carries an idempotency key, so a resend returns the
same episode. A step carries ``t``, so a resend after a lost response returns the original
response rather than taking the action twice. Forfeiting twice is a no-op.
"""

from __future__ import annotations

import os
import random
import time
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import httpx

from jackdaw_arena.spec import Spec

DEFAULT_URL = "https://arena.tylerflar.com"
TOKEN_FILE = Path.home() / ".jackdaw-arena" / "token"
RETRY_STATUS = {429, 502, 503, 504}


class ArenaError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


def find_token(token: str | None = None) -> str:
    """The agent token: the argument, ``$ARENA_TOKEN``, or the first line of
    ``~/.jackdaw-arena/token``. Kept out of argv so it doesn't land in shell history."""
    if token:
        return token
    env = os.environ.get("ARENA_TOKEN")
    if env:
        return env.strip()
    if TOKEN_FILE.exists():
        line = TOKEN_FILE.read_text(encoding="utf-8").strip().splitlines()
        if line:
            return line[0].strip()
    raise ArenaError(
        0, "no_token",
        "no agent token: set ARENA_TOKEN or put it in ~/.jackdaw-arena/token "
        "(make one on your account page)",
    )  # fmt: skip


class ArenaClient:
    def __init__(
        self,
        token: str | None = None,
        url: str | None = None,
        *,
        http: Any = None,
        timeout: float = 30.0,
        retries: int = 6,
    ) -> None:
        self.url = (url or os.environ.get("ARENA_URL") or DEFAULT_URL).rstrip("/")
        self._token = token
        self.http = http or httpx.Client(timeout=timeout, headers={"User-Agent": "jackdaw-arena"})
        self.retries = retries
        self._spec: Spec | None = None

    # --- transport ------------------------------------------------------------------------------

    def _headers(self, auth: bool) -> dict[str, str]:
        return {"Authorization": f"Bearer {find_token(self._token)}"} if auth else {}

    def request(self, method: str, path: str, *, json: Any = None, auth: bool = True) -> Any:
        delay = 0.5
        for attempt in range(self.retries + 1):
            try:
                r = self.http.request(
                    method, f"{self.url}{path}", json=json, headers=self._headers(auth)
                )
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
            else:
                if r.status_code not in RETRY_STATUS or attempt == self.retries:
                    if r.status_code >= 400:
                        try:
                            body = r.json()
                        except ValueError:
                            body = {}
                        raise ArenaError(
                            r.status_code, body.get("error", "error"), body.get("message", r.text)
                        )
                    return r.json() if r.content else None
                retry_after = r.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
            time.sleep(delay * (0.5 + random.random()))
            delay = min(delay * 2, 16.0)
        raise AssertionError("unreachable")

    # --- the protocol ---------------------------------------------------------------------------

    def spec(self) -> Spec:
        if self._spec is None:
            self._spec = Spec(self.request("GET", "/api/v1/spec", auth=False))
        return self._spec

    def me(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/me")

    def create(
        self,
        n: int = 1,
        track: str = "red-1",
        reward: str = "sparse",
        weights: dict[str, float] | None = None,
        keys: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        keys = list(keys) if keys is not None else [str(uuid.uuid4()) for _ in range(n)]
        body: dict[str, Any] = {"track": track, "keys": keys, "reward": {"kind": reward}}
        if weights:
            body["reward"]["weights"] = weights
        return self.request("POST", "/api/v1/episodes", json=body)["episodes"]

    def step(self, items: Iterable[tuple[str, int, int]]) -> list[dict[str, Any]]:
        steps = [{"id": str(i), "t": int(t), "action": int(a)} for i, t, a in items]
        return self.request("POST", "/api/v1/step", json={"steps": steps})["results"]

    def get(self, episode_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/v1/episodes/{episode_id}")

    def running(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v1/episodes?status=running")

    def forfeit(self, episode_id: str) -> dict[str, Any]:
        return self.request("POST", f"/api/v1/episodes/{episode_id}/forfeit")

    def tape(self, episode_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/episodes/{episode_id}/tape", auth=False)

    def close(self) -> None:
        close = getattr(self.http, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> ArenaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
