"""Secrets kept in the database (the mail password, the Microsoft 365 client
secret), encrypted with a key made from the server's SECRET_KEY. If SECRET_KEY
changes they can no longer be read and have to be entered again."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .. import config


def _box() -> Fernet:
    key = hashlib.sha256(("distributor-sales/report-mail:" + config.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(plain: str | None) -> str | None:
    return _box().encrypt(plain.encode()).decode() if plain else None


def open_(sealed: str | None) -> str | None:
    """The secret, or None when there is none or it cannot be read."""
    if not sealed:
        return None
    try:
        return _box().decrypt(sealed.encode()).decode()
    except (InvalidToken, ValueError):
        return None
