import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings

settings = get_settings()


def encode_token(user_id: uuid.UUID) -> str:
    """Issue a dev JWT. Payload: sub=user_id (str), exp."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
