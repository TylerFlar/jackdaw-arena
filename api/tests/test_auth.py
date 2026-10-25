"""Sign-in (GitHub OAuth, OIDC), sessions and the CSRF guard."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import SecretStr

from arena.auth.oauth import GITHUB_TOKEN, GITHUB_USER, safe_next

CSRF = {"X-Arena-CSRF": "1"}


@pytest.fixture
def github_app(make_app, settings):
    s = settings.model_copy(
        update={
            "github_client_id": "gh-client",
            "github_client_secret": SecretStr("gh-secret"),
            "admin_logins": ["TylerFlar"],
        }
    )
    return make_app(settings=s)


def start_login(client: TestClient, provider: str = "github", next_path: str = "/me") -> dict:
    r = client.get(f"/auth/login/{provider}", params={"next": next_path}, follow_redirects=False)
    assert r.status_code == 303
    url = urlsplit(r.headers["location"])
    return {"url": url, "q": {k: v[0] for k, v in parse_qs(url.query).items()}}


def github_profile(mock: respx.MockRouter, login: str = "octo", uid: int = 42) -> respx.Route:
    token = mock.post(GITHUB_TOKEN).respond(json={"access_token": "gho_x", "token_type": "bearer"})
    mock.get(GITHUB_USER).respond(
        json={"id": uid, "login": login, "name": "Octo Cat", "avatar_url": "https://a/x.png"}
    )
    return token


def test_github_sign_in_creates_a_session(github_app):
    with TestClient(github_app) as client, respx.mock(assert_all_called=True) as mock:
        login = start_login(client)
        q = login["q"]
        assert login["url"].netloc == "github.com"
        assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
        assert "scope" not in q  # the public profile needs no scope
        assert q["redirect_uri"] == "http://testserver/auth/callback/github"
        token = github_profile(mock)
        r = client.get(
            "/auth/callback/github",
            params={"code": "c0de", "state": q["state"]},
            follow_redirects=False,
        )
        assert r.status_code == 303 and r.headers["location"] == "/me"
        sent = parse_qs(token.calls.last.request.content.decode())
        assert sent["code_verifier"][0] and sent["client_secret"] == ["gh-secret"]
        me = client.get("/api/me").json()
        assert me["user"]["login"] == "octo" and me["user"]["is_admin"] is False
        assert client.get("/auth/session").json()["user"]["login"] == "octo"
        set_cookie = r.headers.get_list("set-cookie")
        session = next(c for c in set_cookie if c.startswith("arena_session="))
        assert "HttpOnly" in session and "SameSite=lax" in session


def test_admins_come_from_settings(github_app):
    with TestClient(github_app) as client, respx.mock() as mock:
        q = start_login(client)["q"]
        github_profile(mock, login="TylerFlar", uid=7)
        client.get("/auth/callback/github", params={"code": "c", "state": q["state"]})
        assert client.get("/api/me").json()["user"]["is_admin"] is True


@pytest.mark.parametrize("bad", ["state", "cookie", "code"])
def test_callback_rejects_a_mismatched_or_missing_handshake(github_app, bad):
    with TestClient(github_app) as client, respx.mock(assert_all_called=False) as mock:
        q = start_login(client)["q"]
        github_profile(mock)
        params = {"code": "c", "state": q["state"]}
        if bad == "state":
            params["state"] = "forged"
        elif bad == "code":
            params.pop("code")
        else:
            client.cookies.clear()
        r = client.get("/auth/callback/github", params=params, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/signin?error=")
        assert client.get("/api/me").status_code == 401


def test_provider_errors_are_reported(github_app):
    with TestClient(github_app) as client, respx.mock() as mock:
        q = start_login(client)["q"]
        mock.post(GITHUB_TOKEN).respond(json={"error": "bad_verification_code"})
        r = client.get(
            "/auth/callback/github", params={"code": "c", "state": q["state"]},
            follow_redirects=False,
        )  # fmt: skip
        assert "bad_verification_code" in r.headers["location"]


@pytest.mark.parametrize(
    ("given", "safe"),
    [("/agents/x", "/agents/x"), ("//evil.example", "/"), ("https://evil.example", "/"),
     ("/\\evil.example", "/"), ("", "/"), (None, "/")],
)  # fmt: skip
def test_next_stays_on_site(given, safe):
    assert safe_next(given) == safe


def test_logout_needs_the_csrf_header_and_ends_the_session(github_app):
    with TestClient(github_app) as client, respx.mock() as mock:
        q = start_login(client)["q"]
        github_profile(mock)
        client.get("/auth/callback/github", params={"code": "c", "state": q["state"]})
        assert client.post("/auth/logout").status_code == 403
        cross = client.post("/auth/logout", headers={**CSRF, "Origin": "https://evil.example"})
        assert cross.status_code == 403
        assert client.post("/auth/logout", headers=CSRF).status_code == 204
        assert client.get("/api/me").status_code == 401


def test_session_is_null_when_signed_out(client):
    r = client.get("/auth/session")
    assert r.status_code == 200 and r.json() == {"user": None}


def test_unknown_provider(client):
    r = client.get("/auth/login/github", follow_redirects=False)  # not configured here
    assert r.status_code == 303 and r.headers["location"].startswith("/signin?error=")
    assert client.get("/auth/providers").json() == []


# --- OIDC --------------------------------------------------------------------------------------

ISSUER = "http://idp.test/default"


@pytest.fixture
def oidc_app(make_app, settings):
    s = settings.model_copy(
        update={"oidc_issuer": ISSUER, "oidc_client_id": "arena", "oidc_name": "Dev login",
                "oidc_client_secret": SecretStr("s")},
    )  # fmt: skip
    return make_app(settings=s)


class IdP:
    """A mock OpenID provider: discovery, keys, and a token endpoint minting ``claims``."""

    def __init__(self, mock: respx.MockRouter) -> None:
        self.key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
        self.signer = self.key  # sign with another key to test rejection
        self.claims: dict = {}
        mock.get(f"{ISSUER}/.well-known/openid-configuration").respond(
            json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
            }
        )
        mock.get(f"{ISSUER}/jwks").mock(
            side_effect=lambda _: httpx.Response(
                200, json={"keys": [self.key.as_dict(private=False)]}
            )
        )
        mock.post(f"{ISSUER}/token").mock(side_effect=self._token)

    def _token(self, request: httpx.Request) -> httpx.Response:
        id_token = jwt.encode({"alg": "RS256", "kid": "k1"}, self.claims, self.signer)
        return httpx.Response(200, json={"access_token": "at", "id_token": id_token})


def oidc_claims(nonce: str, over: dict | None = None) -> dict:
    now = int(time.time())
    return {"iss": ISSUER, "aud": "arena", "sub": "user-1", "nonce": nonce, "iat": now,
            "exp": now + 300, "preferred_username": "dev", "name": "Dev"} | (over or {})  # fmt: skip


def test_oidc_sign_in(oidc_app):
    with TestClient(oidc_app) as client, respx.mock() as mock:
        idp = IdP(mock)
        login = start_login(client, "oidc")
        q = login["q"]
        assert login["url"].geturl().startswith(f"{ISSUER}/authorize")
        assert q["scope"] == "openid profile email" and q["nonce"]
        idp.claims = oidc_claims(q["nonce"])
        r = client.get("/auth/callback/oidc", params={"code": "c", "state": q["state"]},
                       follow_redirects=False)  # fmt: skip
        assert r.status_code == 303 and r.headers["location"] == "/me"
        assert client.get("/api/me").json()["user"]["login"] == "dev"
        assert client.get("/auth/providers").json() == [{"id": "oidc", "name": "Dev login"}]


@pytest.mark.parametrize(
    "tamper", [{"nonce": "replayed"}, {"aud": "someone-else"}, {"iss": "http://evil"},
               {"exp": 1}, "other-key"]
)  # fmt: skip
def test_oidc_rejects_bad_tokens(oidc_app, tamper):
    with TestClient(oidc_app) as client, respx.mock() as mock:
        idp = IdP(mock)
        q = start_login(client, "oidc")["q"]
        if tamper == "other-key":
            idp.claims = oidc_claims(q["nonce"])
            idp.signer = RSAKey.generate_key(2048, parameters={"kid": "k1"})
        else:
            idp.claims = oidc_claims(q["nonce"], tamper)
        r = client.get("/auth/callback/oidc", params={"code": "c", "state": q["state"]},
                       follow_redirects=False)  # fmt: skip
        assert r.headers["location"].startswith("/signin?error=")
        assert client.get("/api/me").status_code == 401
