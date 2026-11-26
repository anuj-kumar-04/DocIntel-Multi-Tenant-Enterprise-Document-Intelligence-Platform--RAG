import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import redis.asyncio as aioredis
from app.config import settings
from app.core.logging import logger
from jose import jwt

# In-memory fallback used strictly in test environments when Redis is unavailable
_TEST_REVOKED_JTIS: dict[str, float] = {}
_TEST_REVOKED_USERS: dict[str, int] = {}
_TEST_FAILED_LOGINS: dict[str, tuple[int, float]] = {}


def get_password_hash(password: str) -> str:
    """Hash plaintext password with bcrypt."""
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against bcrypt hash."""
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(
    user_id: uuid.UUID | str,
    org_id: uuid.UUID | str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate signed JWT access token with unique jti identifier."""
    now = datetime.now(UTC)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    now_ms = int(now.timestamp() * 1000)
    to_encode: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "iat_ms": now_ms,
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    user_id: uuid.UUID | str,
    org_id: uuid.UUID | str,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate signed JWT refresh token with unique jti identifier."""
    now = datetime.now(UTC)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    now_ms = int(now.timestamp() * 1000)
    to_encode: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "iat_ms": now_ms,
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


async def revoke_token_jti(jti: str | None, expires_in_seconds: int) -> None:
    """Blacklist a specific token JTI until its natural expiration."""
    if not jti:
        return
    ttl = max(1, int(expires_in_seconds))
    r: aioredis.Redis | None = None
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        await r.setex(f"security:revoked_jti:{jti}", ttl, "1")
    except Exception as e:
        if settings.ENVIRONMENT == "test":
            _TEST_REVOKED_JTIS[jti] = time.time() + ttl
        else:
            logger.warning(f"Failed to store revoked JTI in Redis: {e}")
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass


async def is_token_jti_revoked(jti: str | None) -> bool:
    """Check whether a token JTI has been explicitly revoked."""
    if not jti:
        return False
    r: aioredis.Redis | None = None
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        val = await r.get(f"security:revoked_jti:{jti}")
        if val is not None:
            return True
    except Exception:
        if settings.ENVIRONMENT == "test":
            exp_ts = _TEST_REVOKED_JTIS.get(jti)
            if exp_ts and exp_ts > time.time():
                return True
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
    return False


async def revoke_all_user_tokens(user_id: uuid.UUID | str, ttl_seconds: int | None = None) -> None:
    """Invalidate all previously issued tokens for a user (e.g. upon offboarding)."""
    uid = str(user_id)
    now_ms = int(time.time() * 1000)
    ttl = ttl_seconds or (settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
    r: aioredis.Redis | None = None
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        await r.setex(f"security:revoked_user_before:{uid}", ttl, str(now_ms))
    except Exception as e:
        if settings.ENVIRONMENT == "test":
            _TEST_REVOKED_USERS[uid] = now_ms
        else:
            logger.warning(f"Failed to revoke user sessions in Redis: {e}")
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass


async def is_user_token_revoked(
    user_id: uuid.UUID | str, iat: int | None, iat_ms: int | None = None
) -> bool:
    """Check whether a token was issued before the user's global revocation timestamp."""
    token_ts_ms = iat_ms if iat_ms is not None else (int(iat) * 1000 if iat is not None else None)
    if token_ts_ms is None:
        return False
    uid = str(user_id)
    r: aioredis.Redis | None = None
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        raw = await r.get(f"security:revoked_user_before:{uid}")
        if raw is not None and token_ts_ms <= int(raw):
            return True
    except Exception:
        if settings.ENVIRONMENT == "test":
            revoked_ms = _TEST_REVOKED_USERS.get(uid)
            if revoked_ms is not None and token_ts_ms <= revoked_ms:
                return True
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
    return False


async def is_login_locked(email: str) -> bool:
    """Return True if an email account is temporarily locked after repeated failures."""
    key_email = email.lower().strip()
    r: aioredis.Redis | None = None
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        raw = await r.get(f"security:login_failures:{key_email}")
        if raw is not None and int(raw) >= settings.ACCOUNT_LOCKOUT_MAX_ATTEMPTS:
            return True
    except Exception:
        if settings.ENVIRONMENT == "test":
            entry = _TEST_FAILED_LOGINS.get(key_email)
            if (
                entry
                and entry[1] > time.time()
                and entry[0] >= settings.ACCOUNT_LOCKOUT_MAX_ATTEMPTS
            ):
                return True
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
    return False


async def record_failed_login(email: str) -> int:
    """Increment failed login attempt counter with sliding lockout window."""
    key_email = email.lower().strip()
    r: aioredis.Redis | None = None
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        redis_key = f"security:login_failures:{key_email}"
        count = await r.incr(redis_key)
        if count == 1:
            await r.expire(redis_key, settings.ACCOUNT_LOCKOUT_SECONDS)
        return int(count)
    except Exception:
        if settings.ENVIRONMENT == "test":
            now = time.time()
            prev = _TEST_FAILED_LOGINS.get(key_email)
            count = (prev[0] + 1) if (prev and prev[1] > now) else 1
            _TEST_FAILED_LOGINS[key_email] = (count, now + settings.ACCOUNT_LOCKOUT_SECONDS)
            return count
        return 0
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass


async def clear_failed_logins(email: str) -> None:
    """Reset failed login counter upon successful authentication."""
    key_email = email.lower().strip()
    r: aioredis.Redis | None = None
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        await r.delete(f"security:login_failures:{key_email}")
    except Exception:
        if settings.ENVIRONMENT == "test":
            _TEST_FAILED_LOGINS.pop(key_email, None)
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
