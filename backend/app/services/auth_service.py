import re
import secrets
import time
import uuid
from datetime import UTC, datetime

from app.config import settings
from app.core.errors import AuthenticationFailedError, DocIntelException
from app.core.security import (
    clear_failed_logins,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    is_login_locked,
    is_token_jti_revoked,
    is_user_token_revoked,
    record_failed_login,
    revoke_all_user_tokens,
    revoke_token_jti,
    verify_password,
)
from app.models.org import Organization
from app.models.user import User, UserRole
from app.schemas.auth import (
    MemberInviteRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


def slugify(text: str) -> str:
    """Convert text to URL-friendly lowercase slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register_org_and_owner(self, req: UserRegisterRequest) -> tuple[User, TokenResponse]:
        """Atomically create an organization and its primary owner user."""
        user_check = await self.db.execute(select(User).where(User.email == req.email.lower()))
        if user_check.scalars().first():
            raise DocIntelException(
                "A user with this email address already exists", status_code=409
            )

        base_slug = req.org_slug if req.org_slug else slugify(req.org_name)
        slug = base_slug
        counter = 1
        while True:
            slug_check = await self.db.execute(
                select(Organization).where(Organization.slug == slug)
            )
            if not slug_check.scalars().first():
                break
            slug = f"{base_slug}-{counter}"
            counter += 1

        org = Organization(
            name=req.org_name,
            slug=slug,
            plan="enterprise",
            monthly_token_budget=settings.DEFAULT_MONTHLY_TOKEN_BUDGET,
            tokens_used_this_month=0,
        )
        self.db.add(org)
        await self.db.flush()

        user = User(
            org_id=org.id,
            email=req.email.lower(),
            hashed_password=get_password_hash(req.password),
            full_name=req.full_name,
            role=UserRole.OWNER,
            is_active=True,
            last_login_at=datetime.now(UTC),
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(org)

        access_token = create_access_token(user.id, org.id, user.role.value)
        refresh_token = create_refresh_token(user.id, org.id)

        tokens = TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
        user.organization = org
        return user, tokens

    async def authenticate_user(self, req: UserLoginRequest) -> tuple[User, TokenResponse]:
        """Verify user credentials with brute-force lockout protection and issue JWT tokens."""
        normalized_email = req.email.lower()
        if await is_login_locked(normalized_email):
            raise DocIntelException(
                "Too many failed login attempts. Account temporarily locked; please try again later.",
                status_code=429,
            )

        stmt = (
            select(User)
            .where(User.email == normalized_email)
            .options(selectinload(User.organization))
        )
        result = await self.db.execute(stmt)
        user = result.scalars().first()

        if not user or not verify_password(req.password, user.hashed_password):
            await record_failed_login(normalized_email)
            raise AuthenticationFailedError("Invalid email or password")

        if not user.is_active:
            raise AuthenticationFailedError("Account has been disabled. Please contact your admin.")

        await clear_failed_logins(normalized_email)
        user.last_login_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(user)

        access_token = create_access_token(user.id, user.org_id, user.role.value)
        refresh_token = create_refresh_token(user.id, user.org_id)

        tokens = TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
        return user, tokens

    async def refresh_user_token(self, refresh_token: str) -> TokenResponse:
        """Validate refresh token, rotate JTI to prevent replay, and issue fresh tokens."""
        try:
            payload = decode_token(refresh_token)
            if payload.get("type") != "refresh":
                raise AuthenticationFailedError("Invalid token type")
            user_id = uuid.UUID(payload.get("sub"))
            jti = payload.get("jti")
            iat = payload.get("iat")
            iat_ms = payload.get("iat_ms")
            exp = payload.get("exp")
        except Exception:
            raise AuthenticationFailedError("Invalid or expired refresh token") from None

        if await is_token_jti_revoked(jti) or await is_user_token_revoked(user_id, iat, iat_ms):
            raise AuthenticationFailedError("Refresh token has been revoked")

        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalars().first()

        if not user or not user.is_active:
            raise AuthenticationFailedError("User no longer exists or is inactive")

        # Rotate consumed refresh token to prevent replay
        if jti and exp:
            remaining_ttl = max(1, int(exp) - int(time.time()))
            await revoke_token_jti(jti, remaining_ttl)

        new_access_token = create_access_token(user.id, user.org_id, user.role.value)
        new_refresh_token = create_refresh_token(user.id, user.org_id)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def invite_member(self, inviter: User, req: MemberInviteRequest) -> User:
        """Invite/create a member belonging to inviter's organization with privilege guards."""
        if req.role == UserRole.OWNER:
            raise DocIntelException(
                "Cannot assign Owner role via team invitation.", status_code=403
            )
        if inviter.role == UserRole.ADMIN and req.role == UserRole.ADMIN:
            raise DocIntelException(
                "Only organization owners can invite administrators.", status_code=403
            )

        existing = await self.db.execute(select(User).where(User.email == req.email.lower()))
        if existing.scalars().first():
            raise DocIntelException(
                "A user with this email address already exists", status_code=409
            )

        raw_password = req.password or f"{secrets.token_urlsafe(12)}A1!"
        member = User(
            org_id=inviter.org_id,
            email=req.email.lower(),
            hashed_password=get_password_hash(raw_password),
            full_name=req.full_name,
            role=req.role,
            is_active=True,
        )
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(member)
        return member

    async def list_org_members(self, org_id: uuid.UUID) -> list[User]:
        """List all members belonging strictly to the specified tenant organization."""
        stmt = select(User).where(User.org_id == org_id).order_by(User.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_member(self, current_user: User, member_id: uuid.UUID) -> None:
        """Remove a member from the organization with RBAC checks and instant session revocation."""
        if current_user.id == member_id:
            raise DocIntelException(
                "You cannot remove your own account from the organization management console.",
                status_code=400,
            )

        stmt = select(User).where(User.id == member_id, User.org_id == current_user.org_id)
        result = await self.db.execute(stmt)
        target_member = result.scalars().first()

        if not target_member:
            raise DocIntelException("Team member not found in your organization.", status_code=404)

        if target_member.role == UserRole.OWNER:
            raise DocIntelException("The organization owner cannot be removed.", status_code=403)

        if current_user.role == UserRole.ADMIN and target_member.role == UserRole.ADMIN:
            raise DocIntelException(
                "Administrators cannot remove other administrators.", status_code=403
            )

        deleted_id = target_member.id
        await self.db.delete(target_member)
        await self.db.commit()
        await revoke_all_user_tokens(deleted_id)
