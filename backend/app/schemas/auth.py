from datetime import datetime
import uuid
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


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
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=255)
    org_name: str = Field(..., min_length=2, max_length=255)
    org_slug: str | None = None


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


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
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(default="TempPass123!", min_length=8)
    role: UserRole = UserRole.MEMBER


class MemberUpdateRoleRequest(BaseModel):
    role: UserRole
