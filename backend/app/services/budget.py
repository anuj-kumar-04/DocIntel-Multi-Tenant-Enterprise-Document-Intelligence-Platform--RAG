import uuid

from app.core.errors import QuotaExceededError
from app.core.logging import logger
from app.models.org import Organization
from app.models.usage import UsageEvent
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class BudgetService:
    """Manages and enforces per-tenant monthly token budgets."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def assert_within_limit(self, org_id: uuid.UUID) -> Organization:
        """Check if organization has remaining token budget. Raise 429 if exceeded."""
        stmt = select(Organization).where(Organization.id == org_id)
        result = await self.db.execute(stmt)
        org = result.scalars().first()

        if not org:
            raise QuotaExceededError("Organization record not found")

        if org.tokens_used_this_month >= org.monthly_token_budget:
            logger.warning(
                f"Org {org_id} exceeded token quota: {org.tokens_used_this_month}/{org.monthly_token_budget}"
            )
            raise QuotaExceededError(
                f"Monthly token budget of {org.monthly_token_budget:,} tokens has been reached. "
                "Please upgrade your plan or request a budget increase."
            )

        return org

    async def record_usage(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID | None,
        tokens: int,
        cost_usd: float,
        event_type: str = "chat",
    ) -> None:
        """Atomically increment tokens consumed and insert a usage audit event."""
        if tokens <= 0 and cost_usd <= 0:
            return

        # 1. Update organization monthly counter
        upd = (
            update(Organization)
            .where(Organization.id == org_id)
            .values(tokens_used_this_month=Organization.tokens_used_this_month + tokens)
        )
        await self.db.execute(upd)

        # 2. Insert granular usage event
        event = UsageEvent(
            org_id=org_id,
            user_id=user_id,
            event_type=event_type,
            tokens=tokens,
            cost_usd=cost_usd,
        )
        self.db.add(event)
        await self.db.commit()
