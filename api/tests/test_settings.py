from __future__ import annotations

import pytest

from arena.settings import load_settings


@pytest.fixture
def prod(monkeypatch):
    for k in ("ARENA_SSM_PATH", "ARENA_SESSION_SECRET", "ARENA_ORIGIN_VERIFY_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ARENA_ENV", "prod")
    monkeypatch.setenv("ARENA_PUBLIC_URL", "https://arena.example.com")
    return monkeypatch


def test_production_refuses_development_defaults(prod):
    with pytest.raises(RuntimeError, match="session_secret.*origin_verify_secret"):
        load_settings()
    prod.setenv("ARENA_PUBLIC_URL", "http://arena.example.com")
    with pytest.raises(RuntimeError, match="isn't https"):
        load_settings()


def test_production_starts_with_its_secrets(prod):
    prod.setenv("ARENA_SESSION_SECRET", "s" * 48)
    prod.setenv("ARENA_ORIGIN_VERIFY_SECRET", "o" * 40)
    s = load_settings()
    assert s.env == "prod" and s.session_cookie == "__Host-arena_session"
