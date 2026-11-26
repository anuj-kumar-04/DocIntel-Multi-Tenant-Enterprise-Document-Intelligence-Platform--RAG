import uuid
from datetime import datetime
from typing import Any

from app.models.user import UserRole
from pydantic import BaseModel, ConfigDict, Field


class TenantUsageResponse(BaseModel):
    org_id: uuid.UUID
    org_name: str
    monthly_token_budget: int
    tokens_used_this_month: int
    budget_utilized_percent: float
    total_cost_usd: float
    documents_count: int
    chunks_count: int
    conversations_count: int
    messages_count: int
    top_users: list[dict] = []


class UpdateBudgetRequest(BaseModel):
    monthly_token_budget: int = Field(..., gt=0)


class MemberResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    ip_address: str | None = None
    status: str
    details: dict[str, Any] | None = None
    created_at: datetime
