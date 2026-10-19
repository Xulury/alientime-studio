"""Password hashing and token helpers (standard library only)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_MAXMEM = 128 * 1024 * 1024

MIN_PASSWORD_LENGTH = 10


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
                            maxmem=_MAXMEM, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r), p=int(p),
                              maxmem=_MAXMEM, dklen=len(_unb64(digest)))
        return hmac.compare_digest(calc, _unb64(digest))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    """Returns a human-readable reason the password is too weak, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if password.lower() in {"password123", "alientime123", "changeme123", "1234567890"}:
        return "Choose a less common password."
    if len(set(password)) < 5:
        return "Use a more varied password."
    return None


def new_secret_token(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
