"""The client against a scripted server (respx): decoding, spaces, retries, env and evaluate."""

from __future__ import annotations

import base64
import json
import uuid

import httpx
import numpy as np
import pytest
import respx

from jackdaw_arena import ArenaClient, ArenaEnv, evaluate, find_token, random_chooser
from jackdaw_arena.client import ArenaError

URL = "http://arena.test"
FIELDS = [
    {"name": "global", "shape": [235], "offset": 0},
    {"name": "hand_card", "shape": [8, 15], "offset": 235},
    {"name": "joker", "shape": [5, 15], "offset": 355},
    {"name": "consumable", "shape": [2, 7], "offset": 430},
    {"name": "shop_item", "shape": [10, 9], "offset": 444},
    {"name": "pack_card", "shape": [5, 15], "offset": 534},
    {"name": "entity_counts", "shape": [5], "offset": 609},
]
SPEC = {
    "engine_version": "0.2.0", "action_version": 2, "max_actions": 500,
    "obs": {"length": 614, "dtype": "<f4", "fields": FIELDS},
    "action_types": [], "rewards": {"kinds": ["sparse"], "shaped_weights": []},
    "tracks": [{"key": "red-1", "name": "Red", "episodes_per_agent": 500}], "limits": {},
}  # fmt: skip


def obs_b64(value: float) -> str:
    return base64.b64encode(np.full(614, value, dtype="<f4").tobytes()).decode()


class Server:
    """A tiny scripted Arena: every episode lasts ``length`` steps."""

    def __init__(self, mock: respx.MockRouter, length: int = 3) -> None:
        self.length, self.episodes, self.created, self.forfeited = length, {}, [], []
        self.running_ids: list[str] = []
        mock.get(f"{URL}/api/v1/spec").respond(json=SPEC)
        mock.post(f"{URL}/api/v1/episodes").mock(side_effect=self.create)
        mock.post(f"{URL}/api/v1/step").mock(side_effect=self.step)
        mock.get(f"{URL}/api/v1/episodes").mock(
            side_effect=lambda r: httpx.Response(
                200, json=[{"id": i, "key": i, "t": self.episodes[i], "track": "red-1"}
                           for i in self.running_ids]))  # fmt: skip
        mock.get(url__regex=rf"{URL}/api/v1/episodes/[^/]+$").mock(side_effect=self.get)
        mock.post(url__regex=rf"{URL}/api/v1/episodes/[^/]+/forfeit").mock(side_effect=self.forfeit)

    def create(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer jdk_test"
        body = json.loads(request.content)
        out = []
        for k in body["keys"]:
            self.episodes[k] = 0
            self.created.append(k)
            out.append({"id": k, "key": k, "status": "running", "t": 0, "obs": obs_b64(0),
                        "n_actions": 4, "final": None})  # fmt: skip
        return httpx.Response(201, json={"episodes": out})

    def final(self, eid: str) -> dict:
        return {"end_reason": "lost", "won": False, "ante_reached": 1, "rounds_beaten": 2,
                "length": self.length, "seed": f"SEED-{eid[:4]}", "rng_seed": "7",
                "final_state_hash": "h", "verified": True}  # fmt: skip

    def step(self, request: httpx.Request) -> httpx.Response:
        results = []
        for s in json.loads(request.content)["steps"]:
            t = self.episodes[s["id"]]
            assert s["t"] == t and 0 <= s["action"] < 4
            t += 1
            self.episodes[s["id"]] = t
            done = t == self.length
            results.append({"id": s["id"], "ok": True, "t": t, "obs": obs_b64(t),
                            "n_actions": 0 if done else 4, "reward": 1.0 if done else 0.0,
                            "terminated": done, "truncated": False,
                            "final": self.final(s["id"]) if done else None})  # fmt: skip
        return httpx.Response(200, json={"results": results})

    def get(self, request: httpx.Request) -> httpx.Response:
        eid = request.url.path.rsplit("/", 1)[1]
        t = self.episodes[eid]
        return httpx.Response(200, json={"id": eid, "key": eid, "status": "running", "t": t,
                                         "obs": obs_b64(t), "n_actions": 4, "final": None})  # fmt: skip

    def forfeit(self, request: httpx.Request) -> httpx.Response:
        eid = request.url.path.split("/")[-2]
        self.forfeited.append(eid)
        return httpx.Response(200, json={**self.final(eid), "end_reason": "forfeit"})


@pytest.fixture
def server():
    with respx.mock(assert_all_called=False) as mock:
        yield Server(mock)


@pytest.fixture
def client() -> ArenaClient:
    return ArenaClient("jdk_test", URL, retries=3)


def test_spec_spaces_match_the_gymnasium_env(client, server):
    spec = client.spec()
    space = spec.observation_space()
    # gymnasium sorts a Dict space's keys, as for BalatroGymnasiumEnv's own space.
    assert sorted(space.spaces) == sorted(f["name"] for f in FIELDS)
    assert space["hand_card"].shape == (8, 15) and space["global"].dtype == np.float32
    assert list(space["entity_counts"].high) == [8, 5, 2, 10, 5]
    obs = spec.decode(obs_b64(1.5))
    assert obs["joker"].shape == (5, 15) and (obs["global"] == 1.5).all()
    obs["global"][0] = 0  # writable
    assert spec.mask(3).tolist()[:4] == [True, True, True, False] and spec.mask(3).sum() == 3
    with pytest.raises(ValueError):
        spec.decode(base64.b64encode(b"\0" * 8).decode())


def test_env_plays_an_episode_like_balatro_gymnasium_env(client, server):
    env = ArenaEnv(client)
    obs, info = env.reset()
    assert env.observation_space.contains(obs) and info["action_mask"].sum() == 4
    done, steps = False, 0
    while not done:
        obs, reward, term, trunc, info = env.step(int(np.flatnonzero(env.action_masks())[0]))
        steps, done = steps + 1, term or trunc
    assert steps == 3 and reward == 1.0 and info["balatro/rounds_beaten"] == 2
    assert info["arena/seed"].startswith("SEED-") and env.action_masks().sum() == 0
    with pytest.raises(RuntimeError):
        env.step(0)
    env.close()
    assert server.forfeited == []  # nothing running to forfeit


def test_reset_and_close_mid_episode_forfeit(client, server):
    env = ArenaEnv(client)
    env.reset()
    first = env.episode_id
    with pytest.warns(UserWarning, match="forfeits"):
        env.reset()
    with pytest.warns(UserWarning) as caught:
        env.reset(seed=3)
    assert {"ignored", "forfeits"} <= {w for c in caught for w in str(c.message).split()}
    env.close()
    assert server.forfeited[0] == first and len(server.forfeited) == 3


def test_evaluate_plays_exactly_the_budget(client, server):
    result = evaluate(random_chooser(0), 7, batch=3, client=client, progress=False)
    assert len(result.results) == 7 and len(server.created) == 7
    s = result.summary()
    assert s["episodes"] == 7 and s["blinds_beaten"] == 2 and s["length"] == 3 and s["verified"]


def test_evaluate_adopts_running_episodes(client, server):
    left = str(uuid.uuid4())
    server.episodes[left] = 1
    server.running_ids = [left]
    result = evaluate(random_chooser(0), 2, client=client, progress=False)
    assert {r.id for r in result.results} >= {left} and len(server.created) == 1


def test_retries_transient_failures():
    with respx.mock() as mock:
        route = mock.get(f"{URL}/api/v1/spec").mock(
            side_effect=[
                httpx.Response(503),
                httpx.ConnectError("down"),
                httpx.Response(200, json=SPEC),
            ]
        )
        c = ArenaClient("jdk_test", URL, retries=3)
        import jackdaw_arena.client as mod

        mod.time.sleep = lambda s: None  # don't actually wait
        assert c.spec().max_actions == 500 and route.call_count == 3


def test_errors_carry_the_server_code():
    with respx.mock() as mock:
        mock.get(f"{URL}/api/v1/me").respond(401, json={"error": "unauthorized", "message": "no"})
        with pytest.raises(ArenaError) as e:
            ArenaClient("jdk_test", URL).me()
        assert e.value.status == 401 and e.value.code == "unauthorized"


def test_token_lookup(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_TOKEN", "jdk_env")
    assert find_token() == "jdk_env" and find_token("jdk_arg") == "jdk_arg"
    monkeypatch.delenv("ARENA_TOKEN")
    import jackdaw_arena.client as mod

    f = tmp_path / "token"
    f.write_text("jdk_file\n")
    monkeypatch.setattr(mod, "TOKEN_FILE", f)
    assert find_token() == "jdk_file"
    f.unlink()
    with pytest.raises(ArenaError):
        find_token()


# --- verify: with whichever jackdaw is installed ----------------------------------------------


def fake_jackdaw(monkeypatch, version: str, *, rules: str = "same") -> None:
    """A stand-in jackdaw: its final state hash is a digest of the actions, with "changed"
    rules mixed in, and a "refused" action an engine of that version won't play."""
    import hashlib
    import sys
    import types

    class Game:
        def __init__(self) -> None:
            self.played: list[str] = []

        @classmethod
        def new(cls, back: str, stake: int, seed: str) -> Game:
            return cls()

        def step(self, action: object) -> None:
            if action == ["Refused"]:
                raise RuntimeError("not legal here")
            self.played.append(json.dumps(action))

        def state_hash(self) -> str:
            extra = "" if rules == "same" else rules
            return hashlib.sha256(("|".join(self.played) + extra).encode()).hexdigest()

    core = types.ModuleType("jackdaw._core")
    core.__version__ = version
    public = types.ModuleType("jackdaw.core")
    public.Game = Game
    package = types.ModuleType("jackdaw")
    package._core, package.core = core, public
    for name, module in (("jackdaw", package), ("jackdaw._core", core), ("jackdaw.core", public)):
        monkeypatch.setitem(sys.modules, name, module)


def a_tape(actions: list[object], version: str = "0.2.0") -> dict:
    import hashlib

    digest = hashlib.sha256("|".join(json.dumps(a) for a in actions).encode()).hexdigest()
    return {"id": "e1", "engine_version": version, "back": "b_red", "stake": 1, "seed": "S",
            "tape": actions, "final_state_hash": digest}  # fmt: skip


def test_verify_accepts_any_version_that_reproduces_the_final_state(monkeypatch):
    from jackdaw_arena.cli import verify

    tape = a_tape([["SkipBlind"], ["PlayHand", [0, 1]]])
    fake_jackdaw(monkeypatch, "0.2.0")
    assert verify(tape).status == "verified"
    fake_jackdaw(monkeypatch, "0.2.1")  # a release that kept the rules
    v = verify(tape)
    assert v.status == "verified" and "with 0.2.1, recorded with 0.2.0" in v.message


def test_verify_tells_a_wrong_record_from_a_rules_change(monkeypatch):
    from jackdaw_arena.cli import verify

    tape = a_tape([["SkipBlind"]])
    tape["final_state_hash"] = "0" * 64  # the record doesn't match its own engine
    fake_jackdaw(monkeypatch, "0.2.0")
    assert verify(tape).status == "mismatch"
    fake_jackdaw(monkeypatch, "0.3.0", rules="changed")
    v = verify(a_tape([["SkipBlind"]]))
    assert v.status == "inconclusive" and "--tag v0.2.0" in v.message
    v = verify(a_tape([["Refused"]]))  # 0.3.0 won't even play it
    assert v.status == "inconclusive" and "won't play" in v.message


def test_verify_exit_codes(monkeypatch, tmp_path):
    from jackdaw_arena.cli import main

    fake_jackdaw(monkeypatch, "0.2.1")
    path = tmp_path / "tape.json"
    wrong = {**a_tape([["SkipBlind"]]), "final_state_hash": "x"}
    for tape, code in ((a_tape([["SkipBlind"]]), 0), (wrong, 2)):
        path.write_text(json.dumps(tape))
        with pytest.raises(SystemExit) as e:
            main(["--url", URL, "verify", str(path)])
        assert e.value.code == code
