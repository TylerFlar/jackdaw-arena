"""Opaque secrets: agent API tokens and browser session ids. Only SHA-256 digests are stored.

These are 256-bit random values, not passwords, so a plain hash is the right tool: nothing to
brute-force, and the lookup stays a single indexed equality.
"""

from __future__ import annotations

import hashlib
import secrets

TOKEN_PREFIX = "jdk_"


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def display_prefix(token: str) -> str:
    """What the account page shows to tell tokens apart: ``jdk_`` and 6 characters."""
    return token[: len(TOKEN_PREFIX) + 6]
