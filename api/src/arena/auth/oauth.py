"""Sign-in: GitHub (OAuth 2) and any OpenID Connect provider.

The authorization-code flow with PKCE (S256) and a ``state`` check. For OIDC there's also a
``nonce`` and an ID token verified against the provider's keys. The handshake's secrets live
in a short-lived signed cookie scoped to ``/auth``. No scopes are requested from GitHub: the
public profile is all the Arena needs, and the access token is dropped right after reading it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from itsdangerous import BadSignature, URLSafeTimedSerializer
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from arena.settings import Settings

HANDSHAKE_COOKIE = "arena_oauth"
HANDSHAKE_MAX_AGE = 600


class SignInError(Exception):
    pass


@dataclass(frozen=True)
class Identity:
    provider: str
    subject: str
    login: str
    name: str | None
    avatar_url: str | None


@dataclass
class Provider:
    id: str
    name: str
    client_id: str
    client_secret: str
    authorize_url: str = ""
    token_url: str = ""
    issuer: str | None = None  # OIDC only
    jwks_uri: str | None = None
    discovered_at: float = 0.0

    @property
    def oidc(self) -> bool:
        return self.issuer is not None


GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_USER = "https://api.github.com/user"


class SignIn:
    """The configured providers and the flow between them and the Arena."""

    def __init__(self, settings: Settings, http: httpx.Client) -> None:
        self.settings, self.http = settings, http
        self.serializer = URLSafeTimedSerializer(
            settings.session_secret.get_secret_value(), salt="arena-oauth-handshake"
        )
        self.providers: dict[str, Provider] = {}
        if settings.github_client_id and settings.github_client_secret:
            self.providers["github"] = Provider(
                "github", "GitHub", settings.github_client_id,
                settings.github_client_secret.get_secret_value(), GITHUB_AUTHORIZE, GITHUB_TOKEN,
            )  # fmt: skip
        if settings.oidc_issuer and settings.oidc_client_id:
            secret = (
                settings.oidc_client_secret.get_secret_value()
                if (settings.oidc_client_secret)
                else ""
            )
            self.providers["oidc"] = Provider(
                "oidc", settings.oidc_name, settings.oidc_client_id, secret,
                issuer=settings.oidc_issuer.rstrip("/"),
            )  # fmt: skip
        self._jwks: dict[str, tuple[float, Any]] = {}

    def listing(self) -> list[dict[str, str]]:
        return [{"id": p.id, "name": p.name} for p in self.providers.values()]

    def redirect_uri(self, provider: str) -> str:
        return f"{self.settings.public_url.rstrip('/')}/auth/callback/{provider}"

    # --- step 1: send the browser to the provider ----------------------------------------------

    def begin(self, provider_id: str, next_path: str) -> tuple[str, str]:
        """The provider URL to redirect to and the handshake cookie value to set."""
        p = self._provider(provider_id)
        if p.oidc:
            self._discover(p)
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        params = {
            "client_id": p.client_id,
            "redirect_uri": self.redirect_uri(p.id),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "response_type": "code",
        }
        nonce = None
        if p.oidc:
            nonce = secrets.token_urlsafe(24)
            params |= {"scope": "openid profile email", "nonce": nonce}
        cookie = self.serializer.dumps(
            {"p": p.id, "s": state, "v": verifier, "n": nonce, "next": safe_next(next_path)}
        )
        return f"{p.authorize_url}?{urlencode(params)}", cookie

    # --- step 2: the provider sends the browser back -------------------------------------------

    def finish(
        self, provider_id: str, code: str | None, state: str | None, cookie: str | None
    ) -> tuple[Identity, str]:
        """Verify the callback, exchange the code, and return who signed in and where to go."""
        p = self._provider(provider_id)
        if not cookie:
            raise SignInError("the sign-in expired or cookies are blocked; try again")
        try:
            hs = self.serializer.loads(cookie, max_age=HANDSHAKE_MAX_AGE)
        except BadSignature:
            raise SignInError("the sign-in expired; try again") from None
        if hs.get("p") != p.id or not state or not hmac.compare_digest(hs["s"], state):
            raise SignInError("the sign-in didn't match this browser; try again")
        if not code:
            raise SignInError("the provider didn't sign you in")
        token = self._exchange(p, code, hs["v"])
        identity = self._oidc_identity(p, token, hs["n"]) if p.oidc else self._github(token)
        return identity, hs["next"]

    def _exchange(self, p: Provider, code: str, verifier: str) -> dict[str, Any]:
        r = self.http.post(
            p.token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri(p.id),
                "client_id": p.client_id,
                "client_secret": p.client_secret,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or "error" in body or "access_token" not in body:
            raise SignInError(
                f"the provider refused the sign-in ({body.get('error', r.status_code)})"
            )
        return body

    def _github(self, token: dict[str, Any]) -> Identity:
        r = self.http.get(
            GITHUB_USER,
            headers={
                "Authorization": f"Bearer {token['access_token']}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        if r.status_code != 200:
            raise SignInError("couldn't read your GitHub profile")
        u = r.json()
        return Identity("github", str(u["id"]), u["login"], u.get("name"), u.get("avatar_url"))

    def _oidc_identity(self, p: Provider, token: dict[str, Any], nonce: str | None) -> Identity:
        id_token = token.get("id_token")
        if not id_token:
            raise SignInError("the provider sent no ID token")
        issuers = [p.issuer]
        if self.settings.oidc_internal_issuer:
            issuers.append(self.settings.oidc_internal_issuer.rstrip("/"))
        try:
            token = jwt.decode(id_token, self._keys(p), algorithms=["RS256", "ES256"])
            claims = token.claims
            jwt.JWTClaimsRegistry(
                leeway=60,
                iss={"essential": True, "values": issuers},
                aud={"essential": True, "value": p.client_id},
                exp={"essential": True},
                sub={"essential": True},
                nonce={"essential": True, "value": nonce},
            ).validate(claims)
        except (JoseError, ValueError) as exc:
            raise SignInError(f"the ID token didn't verify ({exc})") from None
        login = claims.get("preferred_username") or claims.get("email") or claims["sub"]
        return Identity(
            f"oidc:{claims['iss']}", str(claims["sub"]), str(login), claims.get("name"),
            claims.get("picture"),
        )  # fmt: skip

    # --- provider metadata ---------------------------------------------------------------------

    def _provider(self, provider_id: str) -> Provider:
        p = self.providers.get(provider_id)
        if p is None:
            raise SignInError(f"sign-in with {provider_id!r} isn't set up here")
        return p

    def _server_url(self, url: str) -> str:
        """Rewrite a provider URL to how this server reaches it (containers see the IdP at
        another host than browsers do)."""
        internal = self.settings.oidc_internal_issuer
        issuer = self.settings.oidc_issuer
        if internal and issuer and url.startswith(issuer.rstrip("/")):
            return internal.rstrip("/") + url[len(issuer.rstrip("/")) :]
        return url

    def _browser_url(self, url: str) -> str:
        """The inverse of ``_server_url``: where the browser reaches a provider URL."""
        internal = self.settings.oidc_internal_issuer
        issuer = self.settings.oidc_issuer
        if internal and issuer and url.startswith(internal.rstrip("/")):
            return issuer.rstrip("/") + url[len(internal.rstrip("/")) :]
        return url

    def _discover(self, p: Provider) -> None:
        if p.authorize_url and time.time() - p.discovered_at < 3600:
            return
        assert p.issuer is not None
        r = self.http.get(
            self._server_url(f"{p.issuer}/.well-known/openid-configuration"), timeout=10
        )
        if r.status_code != 200:
            raise SignInError("the sign-in provider is unreachable")
        meta = r.json()
        p.authorize_url = self._browser_url(meta["authorization_endpoint"])
        p.token_url = self._server_url(meta["token_endpoint"])
        p.jwks_uri = self._server_url(meta["jwks_uri"])
        p.discovered_at = time.time()

    def _keys(self, p: Provider) -> Any:
        self._discover(p)
        assert p.jwks_uri is not None
        cached = self._jwks.get(p.jwks_uri)
        if cached and time.time() - cached[0] < 3600:
            return cached[1]
        keys = KeySet.import_key_set(self.http.get(p.jwks_uri, timeout=10).json())
        self._jwks[p.jwks_uri] = (time.time(), keys)
        return keys


def safe_next(path: str | None) -> str:
    """Only same-site paths: ``/agents/x`` yes; ``//evil.com``, ``https://...``, ``\\\\`` no."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path
