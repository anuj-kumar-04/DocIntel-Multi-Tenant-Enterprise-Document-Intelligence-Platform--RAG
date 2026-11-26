import uuid
from collections.abc import AsyncGenerator

from app.config import settings
from app.core.security import is_token_jti_revoked, is_user_token_revoked
from app.models.user import User, UserRole
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Async SQLAlchemy Engine & Session Factory
engine_kwargs: dict = {
    "echo": settings.DEBUG and settings.ENVIRONMENT == "development",
    "future": True,
}
if settings.ENVIRONMENT == "test":
    from sqlalchemy.pool import NullPool

    engine_kwargs["poolclass"] = NullPool
elif not settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 10

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

security_bearer = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields a database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            if session.bind and session.bind.dialect.name == "postgresql":
                try:
                    await session.execute(
                        text("SELECT set_config('app.current_org_id', '', false)")
                    )
                except Exception:
                    pass
            await session.close()


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate Bearer JWT access token, check revocation, and bind tenant context."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials:
        raise credentials_exception

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id_str: str | None = payload.get("sub")
        token_org_id: str | None = payload.get("org_id")
        token_type: str | None = payload.get("type")
        token_jti: str | None = payload.get("jti")
        token_iat: int | None = payload.get("iat")
        token_iat_ms: int | None = payload.get("iat_ms")
        token_exp: int | None = payload.get("exp")

        if user_id_str is None or token_org_id is None or token_type != "access":
            raise credentials_exception

        user_id = uuid.UUID(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception from None

    if await is_token_jti_revoked(token_jti) or await is_user_token_revoked(
        user_id, token_iat, token_iat_ms
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await db.get(User, user_id)
    if not user or not user.is_active or str(user.org_id) != token_org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account is deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Set PostgreSQL session tenant context for Row-Level Security (RLS) defense-in-depth
    if db.bind and db.bind.dialect.name == "postgresql":
        try:
            await db.execute(
                text("SELECT set_config('app.current_org_id', :org_id, false)"),
                {"org_id": str(user.org_id)},
            )
        except Exception:
            pass

    # Attach tenant, user, and token state for middleware, logout revocation & telemetry
    request.state.user_id = str(user.id)
    request.state.org_id = str(user.org_id)
    request.state.token_jti = token_jti
    request.state.token_exp = token_exp

    return user


def require_role(required_role: UserRole | str):
    """Enforce minimum role requirement (owner > admin > member)."""
    role_hierarchy = {
        UserRole.MEMBER: 1,
        UserRole.ADMIN: 2,
        UserRole.OWNER: 3,
    }

    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_level = role_hierarchy.get(current_user.role, 0)
        target_role = (
            required_role if isinstance(required_role, UserRole) else UserRole(required_role)
        )
        required_level = role_hierarchy.get(target_role, 99)

        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires {target_role.value} privileges",
            )
        return current_user

    return role_checker
