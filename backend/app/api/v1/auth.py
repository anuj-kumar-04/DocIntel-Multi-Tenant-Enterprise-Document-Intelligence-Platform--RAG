import time

from app.core.errors import AuthenticationFailedError, DocIntelException
from app.core.rate_limit import limiter
from app.core.security import revoke_token_jti
from app.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import (
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.services.audit import AuditService
from app.services.auth_service import AuthService
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    req: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new organization and its initial owner user in a single transaction."""
    auth_service = AuthService(db)
    user, tokens = await auth_service.register_org_and_owner(req)
    await db.refresh(user, attribute_names=["organization"])
    await AuditService(db).log_event(
        action="ORG_REGISTERED",
        resource_type="organization",
        org_id=user.org_id,
        user_id=user.id,
        resource_id=str(user.org_id),
        details={"email": user.email, "org_name": req.org_name},
        request=request,
    )
    return {
        "user": UserResponse.model_validate(user),
        "tokens": tokens,
    }


@router.post("/login", response_model=dict)
@limiter.limit("10/minute")
async def login(
    request: Request,
    req: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with email and password to receive JWT access and refresh tokens."""
    auth_service = AuthService(db)
    audit_svc = AuditService(db)
    try:
        user, tokens = await auth_service.authenticate_user(req)
    except (AuthenticationFailedError, DocIntelException) as exc:
        await audit_svc.log_event(
            action="LOGIN_FAILED",
            resource_type="user",
            status="denied",
            details={"email": req.email.lower(), "reason": exc.message},
            request=request,
        )
        raise

    await db.refresh(user, attribute_names=["organization"])
    await audit_svc.log_event(
        action="LOGIN_SUCCESS",
        resource_type="user",
        org_id=user.org_id,
        user_id=user.id,
        resource_id=str(user.id),
        details={"email": user.email},
        request=request,
    )
    return {
        "user": UserResponse.model_validate(user),
        "tokens": tokens,
    }


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
async def refresh_token(
    request: Request,
    req: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Obtain a new access token using a valid refresh token (rotates old token)."""
    auth_service = AuthService(db)
    return await auth_service.refresh_user_token(req.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current access token JTI immediately."""
    jti = getattr(request.state, "token_jti", None)
    exp = getattr(request.state, "token_exp", None)
    if jti and exp:
        remaining_ttl = max(1, int(exp) - int(time.time()))
        await revoke_token_jti(jti, remaining_ttl)
    await AuditService(db).log_event(
        action="LOGOUT",
        resource_type="user",
        org_id=current_user.org_id,
        user_id=current_user.id,
        resource_id=str(current_user.id),
        request=request,
    )
    return None


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve profile and organization information for the authenticated user."""
    await db.refresh(current_user, attribute_names=["organization"])
    return current_user
