import re
import uuid
from datetime import datetime

from app.models.user import UserRole
from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _validate_email(v: str) -> str:
    cleaned = v.strip().lower()
    if not _EMAIL_REGEX.match(cleaned):
        raise ValueError("Invalid email address format")
    return cleaned


def _validate_strong_password(v: str) -> str:
    if len(v.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 bytes")
    if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("Password must contain at least one letter and one digit")
    return v


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=255)


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    plan: str
    monthly_token_budget: int
    tokens_used_this_month: int
    created_at: datetime


class UserRegisterRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=72)
    full_name: str = Field(..., min_length=2, max_length=255)
    org_name: str = Field(..., min_length=2, max_length=255)
    org_slug: str | None = None

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return _validate_strong_password(v)


class UserLoginRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return _validate_email(v)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None
    organization: OrganizationResponse | None = None


class MemberInviteRequest(BaseModel):
    email: str = Field(..., max_length=255)
    full_name: str = Field(..., min_length=2, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=72)
    role: UserRole = UserRole.MEMBER

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_strong_password(v)


class MemberUpdateRoleRequest(BaseModel):
    role: UserRole
