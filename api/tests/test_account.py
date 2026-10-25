"""The account API: agents, tokens, the owner's views and moderation."""

from __future__ import annotations

import uuid

import numpy as np

from tests.conftest import bearer

CSRF = {"X-Arena-CSRF": "1"}


def test_create_agents_and_tokens(client, agents, sign_in, settings):
    sign_in(client, agents.user("ada"))
    assert client.post("/api/me/agents", json={"slug": "ppo-1", "name": "PPO"}).status_code == 403
    r = client.post(
        "/api/me/agents",
        json={"slug": "ppo-1", "name": "PPO", "description": "MaskablePPO, 30M steps",
              "url": "https://github.com/ada/ppo"},
        headers=CSRF,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "ppo-1" and r.json()["tokens"] == []
    taken = client.post("/api/me/agents", json={"slug": "ppo-1", "name": "x"}, headers=CSRF)
    assert taken.status_code == 409
    for bad in ("x", "Has-Caps", "-dash", "house-random", "a" * 41):
        r = client.post("/api/me/agents", json={"slug": bad, "name": "x"}, headers=CSRF)
        assert r.status_code == 422, bad

    made = client.post("/api/me/agents/ppo-1/tokens", json={"label": "laptop"}, headers=CSRF)
    assert made.status_code == 201
    token = made.json()["token"]
    assert token.startswith("jdk_") and made.json()["prefix"] == token[:10]
    listed = client.get("/api/me").json()["agents"][0]["tokens"]
    assert [t["label"] for t in listed] == ["laptop"] and token not in str(listed)

    assert client.get("/api/v1/me", headers=bearer(token)).json()["agent"] == "ppo-1"
    tid = listed[0]["id"]
    assert client.delete(f"/api/me/tokens/{tid}").status_code == 403  # CSRF
    assert client.delete(f"/api/me/tokens/{tid}", headers=CSRF).status_code == 204
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 401
    assert client.delete(f"/api/me/tokens/{tid}", headers=CSRF).status_code == 404


def test_limits(client, agents, sign_in, settings):
    sign_in(client, agents.user("bo"))
    for i in range(settings.max_agents_per_user):
        r = client.post("/api/me/agents", json={"slug": f"bot-{i}", "name": "b"}, headers=CSRF)
        assert r.status_code == 201
    r = client.post("/api/me/agents", json={"slug": "bot-x", "name": "b"}, headers=CSRF)
    assert r.status_code == 429
    for _ in range(settings.max_tokens_per_agent):
        client.post("/api/me/agents/bot-0/tokens", json={}, headers=CSRF)
    assert client.post("/api/me/agents/bot-0/tokens", json={}, headers=CSRF).status_code == 429


def test_only_the_owner_manages_an_agent(client, agents, sign_in):
    owner = agents.user("owner")
    agents.agent("theirs", user=owner)
    sign_in(client, agents.user("intruder"))
    assert (
        client.patch("/api/me/agents/theirs", json={"name": "x"}, headers=CSRF).status_code == 404
    )
    assert client.post("/api/me/agents/theirs/tokens", json={}, headers=CSRF).status_code == 404
    assert client.get("/api/me/agents/theirs").status_code == 404


def test_unlisted_agents_are_private_to_their_owner(client, agents, sign_in, ended):
    owner = agents.user("quiet")
    agent, token = agents.agent("secret-bot", user=owner, unlisted=True)
    eid = ended(agent, rounds=3)
    assert client.get("/api/agents/secret-bot").status_code == 404
    assert client.get(f"/api/episodes/{eid}").status_code == 404
    assert client.get(f"/api/episodes/{eid}/tape").status_code == 404
    board = client.get("/api/leaderboard").json()
    assert all(r["agent"]["slug"] != "secret-bot" for r in board["provisional"])
    sign_in(client, owner)
    assert client.get("/api/me/agents/secret-bot").json()["agent"]["slug"] == "secret-bot"
    assert client.get(f"/api/me/episodes/{eid}/tape").status_code == 200
    r = client.patch("/api/me/agents/secret-bot", json={"unlisted": False}, headers=CSRF)
    assert r.status_code == 200 and r.json()["unlisted"] is False
    assert client.get("/api/agents/secret-bot").status_code == 200


def test_moderation_is_for_admins(client, agents, sign_in):
    agents.agent("spammy")
    sign_in(client, agents.user("someone"))
    assert (
        client.post("/api/admin/agents/spammy", json={"hidden": True}, headers=CSRF).status_code
        == 403
    )
    sign_in(client, agents.user("mod", admin=True))
    assert (
        client.post("/api/admin/agents/spammy", json={"hidden": True}, headers=CSRF).status_code
        == 200
    )
    assert client.get("/api/agents/spammy").status_code == 404


def test_owner_replays_play_back(client, agents, sign_in):
    owner = agents.user("player")
    agent, token = agents.agent("player-bot", user=owner, unlisted=True)
    r = client.post("/api/v1/episodes", json={"keys": [str(uuid.uuid4())]}, headers=bearer(token))
    ep = r.json()["episodes"][0]
    rng, t, n = np.random.default_rng(1), 0, ep["n_actions"]
    while True:
        res = client.post("/api/v1/step", json={"steps": [{"id": ep["id"], "t": t,
                          "action": int(rng.integers(n))}]}, headers=bearer(token))  # fmt: skip
        out = res.json()["results"][0]
        if out["final"]:
            break
        t, n = out["t"], out["n_actions"]
    sign_in(client, owner)
    frames = client.get(f"/api/me/episodes/{ep['id']}/frames").json()
    assert frames["total"] == out["t"] + 1 and len(frames["frames"]) == frames["total"]
