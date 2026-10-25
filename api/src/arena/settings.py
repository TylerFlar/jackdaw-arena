"""Configuration: ``ARENA_*`` environment variables, plus SSM Parameter Store on AWS.

On Lambda the non-secret settings arrive as environment variables (Terraform sets them) and the
secrets are read once per cold start from SSM under ``ARENA_SSM_PATH``. For example,
``/arena/prod/session_secret`` fills ``session_secret``.
"""

from __future__ import annotations

from functools import cached_property
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SESSION_SECRET = "dev-only-session-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARENA_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    build: str = "dev"  # the deployed git SHA; deploys set ARENA_BUILD
    # "api" serves HTTP; "tasks" also runs migrations, the janitor and house baselines; "local"
    # (uvicorn on a laptop) does both.
    role: Literal["api", "tasks", "local"] = "local"

    # Database: plain PostgreSQL (development, tests) or Aurora DSQL with IAM auth (production).
    db: Literal["postgres", "dsql"] = "postgres"
    database_url: str = "postgresql+psycopg://arena:arena@127.0.0.1:54329/arena"
    dsql_endpoint: str | None = None
    dsql_user: str = "arena_app"  # the tasks function connects as "admin"
    dsql_app_role_arn: str | None = None  # the api Lambda's IAM role, mapped to dsql_user
    aws_region: str = "us-west-2"
    ssm_path: str | None = None

    # The site's public origin: OAuth redirect URIs and the Origin check use it.
    public_url: str = "http://localhost:5173"

    session_secret: SecretStr = SecretStr(DEV_SESSION_SECRET)
    session_days: int = 30
    # CloudFront adds this header to every request it forwards. Without it, a request reached
    # the Function URL directly and is refused. Unset outside AWS.
    origin_verify_secret: SecretStr | None = None

    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None
    # A generic OIDC provider (the mock IdP in development, or any SSO provider).
    oidc_issuer: str | None = None
    oidc_internal_issuer: str | None = None  # how the API reaches the issuer, if not via its URL
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_name: str = "Single sign-on"

    admin_logins: list[str] = []

    # Limits.
    cache_size: int = 512
    idle_timeout_s: int = 600
    max_running_per_agent: int = 64
    max_agents_per_user: int = 5
    max_tokens_per_agent: int = 3
    max_batch: int = 256
    max_new_episodes: int = 64

    @property
    def cookie_secure(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def session_cookie(self) -> str:
        # __Host- cookies must be Secure, Path=/ and host-only: the strictest a cookie can be.
        return "__Host-arena_session" if self.cookie_secure else "arena_session"

    @cached_property
    def public_origin(self) -> str:
        from urllib.parse import urlsplit

        u = urlsplit(self.public_url)
        return f"{u.scheme}://{u.netloc}"


def load_settings() -> Settings:
    """Settings from the environment, with SSM parameters filled in when ``ARENA_SSM_PATH`` is
    set. Environment variables win over SSM, so a value can be overridden for debugging."""
    settings = Settings()
    if not settings.ssm_path:
        return check_production(settings)
    import os

    import boto3

    ssm = boto3.client("ssm", region_name=settings.aws_region)
    values: dict[str, str] = {}
    pages = ssm.get_paginator("get_parameters_by_path").paginate(
        Path=settings.ssm_path, Recursive=False, WithDecryption=True
    )
    for page in pages:
        for p in page["Parameters"]:
            values[p["Name"].rsplit("/", 1)[-1]] = p["Value"]
    fields = Settings.model_fields
    overrides = {
        k: v for k, v in values.items() if k in fields and f"ARENA_{k.upper()}" not in os.environ
    }
    return check_production(Settings(**overrides))


def check_production(settings: Settings) -> Settings:
    """Refuse to start in production on development defaults (say, SSM unreadable): the
    deploy's health check fails, so the version never takes traffic."""
    if settings.env != "prod":
        return settings
    problems = []
    if settings.session_secret.get_secret_value() == DEV_SESSION_SECRET:
        problems.append("session_secret is the development default")
    if settings.origin_verify_secret is None:
        problems.append("origin_verify_secret is unset")
    if not settings.cookie_secure:
        problems.append("public_url isn't https")
    if problems:
        raise RuntimeError("refusing to start in production: " + "; ".join(problems))
    return settings
