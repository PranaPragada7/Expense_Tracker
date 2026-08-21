"""Password hashing and short-lived bearer tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

TOKEN_ALGORITHM = "HS256"
TOKEN_ISSUER = "expense-tracker-api"
PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: int, secret: str, minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iss": TOKEN_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, secret, algorithm=TOKEN_ALGORITHM)


def decode_access_token(token: str, secret: str) -> int:
    payload = jwt.decode(
        token,
        secret,
        algorithms=[TOKEN_ALGORITHM],
        issuer=TOKEN_ISSUER,
    )
    subject = payload.get("sub")
    if not subject:
        raise jwt.InvalidTokenError("Token subject is missing")
    try:
        return int(subject)
    except (TypeError, ValueError) as exc:
        raise jwt.InvalidTokenError("Token subject is invalid") from exc
