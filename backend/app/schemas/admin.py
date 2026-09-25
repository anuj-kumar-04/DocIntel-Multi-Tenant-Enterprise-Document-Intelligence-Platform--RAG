from datetime import datetime
import uuid
from pydantic import BaseModel, Field

from app.models.user import UserRole


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
