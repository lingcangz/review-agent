"""Token handling. Only one-way hashes are persisted."""

import base64
import hashlib
import hmac
import secrets


def new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return base64.b64encode(salt + derived).decode("ascii")


def verify_password(password: str, encoded: str) -> bool:
    raw = base64.b64decode(encoded.encode("ascii"))
    expected = raw[16:]
    actual = hashlib.scrypt(password.encode("utf-8"), salt=raw[:16], n=2**14, r=8, p=1)
    return hmac.compare_digest(actual, expected)
