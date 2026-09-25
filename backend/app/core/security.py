from datetime import datetime, timedelta, timezone
from typing import Any
import uuid
from jose import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """Hash plaintext password with bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    user_id: uuid.UUID | str,
    org_id: uuid.UUID | str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate signed JWT access token."""
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    user_id: uuid.UUID | str,
    org_id: uuid.UUID | str,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate signed JWT refresh token."""
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate JWT token claims."""
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
