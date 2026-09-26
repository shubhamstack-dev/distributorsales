"""One shared password, and a signed token for the session.

Deliberately small: this tool has a handful of users inside one company. What
matters is that the API is not open to anyone who can reach the port, which is
enforced in main.py for every route at once rather than route by route.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from .. import config


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def issue_token(who: str = "user") -> str:
    payload = {"who": who[:60], "exp": int(time.time()) + config.TOKEN_HOURS * 3600}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str) -> dict | None:
    try:
        body, sig = token.split(".")
    except ValueError:
        return None
    want = _b64(hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, want):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def password_ok(given: str) -> bool:
    """Constant-time, and refuses when no password is configured rather than
    letting an empty one through."""
    if not config.APP_PASSWORD:
        return False
    return hmac.compare_digest(given or "", config.APP_PASSWORD)
