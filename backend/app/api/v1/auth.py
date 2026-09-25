from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import (
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
async def register(req: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new organization and its initial owner user in a single transaction."""
    auth_service = AuthService(db)
    user, tokens = await auth_service.register_org_and_owner(req)
    return {
        "user": UserResponse.model_validate(user),
        "tokens": tokens,
    }


@router.post("/login", response_model=dict)
async def login(req: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with email and password to receive JWT access and refresh tokens."""
    auth_service = AuthService(db)
    user, tokens = await auth_service.authenticate_user(req)
    return {
        "user": UserResponse.model_validate(user),
        "tokens": tokens,
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """Obtain a new access token using a valid refresh token."""
    auth_service = AuthService(db)
    return await auth_service.refresh_user_token(req.refresh_token)


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve profile and organization information for the authenticated user."""
    # Ensure organization relationship is loaded
    await db.refresh(current_user, attribute_names=["organization"])
    return current_user
