from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db, require_role
from app.models.chat import Conversation, Message
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.org import Organization
from app.models.usage import UsageEvent
from app.models.user import User, UserRole
from app.schemas.admin import MemberResponse, TenantUsageResponse, UpdateBudgetRequest
from app.schemas.auth import MemberInviteRequest
from app.services.auth_service import AuthService

router = APIRouter(prefix="/admin", tags=["Admin & Tenant Governance"])


@router.get("/usage", response_model=TenantUsageResponse)
async def get_tenant_usage(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve comprehensive token consumption, cost, and usage metrics for the tenant."""
    org_id = current_user.org_id

    # 1. Fetch organization details
    org = await db.get(Organization, org_id)

    # 2. Count documents
    doc_count_res = await db.execute(
        select(func.count(Document.id)).where(Document.org_id == org_id)
    )
    docs_count = doc_count_res.scalar() or 0

    # 3. Count chunks
    chunk_count_res = await db.execute(
        select(func.count(Chunk.id)).where(Chunk.org_id == org_id)
    )
    chunks_count = chunk_count_res.scalar() or 0

    # 4. Count conversations
    conv_count_res = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.org_id == org_id)
    )
    convs_count = conv_count_res.scalar() or 0

    # 5. Count messages
    msg_count_res = await db.execute(
        select(func.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.org_id == org_id)
    )
    msgs_count = msg_count_res.scalar() or 0

    # 6. Sum cost from usage events
    cost_res = await db.execute(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0.0)).where(
            UsageEvent.org_id == org_id
        )
    )
    total_cost = float(cost_res.scalar() or 0.0)

    # 7. Aggregate top active users
    top_users_stmt = (
        select(
            User.email,
            User.full_name,
            func.coalesce(func.sum(UsageEvent.tokens), 0).label("user_tokens"),
        )
        .join(UsageEvent, UsageEvent.user_id == User.id, isouter=True)
        .where(User.org_id == org_id)
        .group_by(User.id, User.email, User.full_name)
        .order_by(func.sum(UsageEvent.tokens).desc())
        .limit(5)
    )
    top_users_res = await db.execute(top_users_stmt)
    top_users = [
        {"email": r[0], "full_name": r[1], "tokens": int(r[2] or 0)}
        for r in top_users_res.fetchall()
    ]

    budget_pct = (
        round((org.tokens_used_this_month / org.monthly_token_budget) * 100, 2)
        if org.monthly_token_budget > 0
        else 0.0
    )

    return TenantUsageResponse(
        org_id=org.id,
        org_name=org.name,
        monthly_token_budget=org.monthly_token_budget,
        tokens_used_this_month=org.tokens_used_this_month,
        budget_utilized_percent=budget_pct,
        total_cost_usd=total_cost,
        documents_count=docs_count,
        chunks_count=chunks_count,
        conversations_count=convs_count,
        messages_count=msgs_count,
        top_users=top_users,
    )


@router.patch("/budget", response_model=TenantUsageResponse)
async def update_token_budget(
    req: UpdateBudgetRequest,
    current_user: User = Depends(require_role(UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    """Update organization monthly token budget (Tenant Owner only)."""
    org = await db.get(Organization, current_user.org_id)
    org.monthly_token_budget = req.monthly_token_budget
    await db.commit()
    await db.refresh(org)
    return await get_tenant_usage(current_user, db)


@router.post("/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def invite_member(
    req: MemberInviteRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Invite a new team member to the tenant organization."""
    auth_svc = AuthService(db)
    member = await auth_svc.invite_member(current_user, req)
    return member


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """List all team members of the tenant organization."""
    auth_svc = AuthService(db)
    return await auth_svc.list_org_members(current_user.org_id)
