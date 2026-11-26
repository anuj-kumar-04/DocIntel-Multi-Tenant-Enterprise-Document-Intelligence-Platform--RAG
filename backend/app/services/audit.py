import uuid
from typing import Any

from app.core.logging import logger
from app.models.audit import AuditLog
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class AuditService:
    """Service for recording and querying tenant-scoped security audit logs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def extract_client_meta(request: Request | None) -> tuple[str | None, str | None]:
        """Extract originating client IP and User-Agent from request headers."""
        if request is None:
            return None, None
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip_address = forwarded.split(",")[0].strip()[:64]
        elif request.client:
            ip_address = request.client.host[:64]
        else:
            ip_address = None
        user_agent = (request.headers.get("User-Agent") or "")[:512] or None
        return ip_address, user_agent

    async def log_event(
        self,
        *,
        action: str,
        resource_type: str,
        org_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        resource_id: str | None = None,
        status: str = "success",
        details: dict[str, Any] | None = None,
        request: Request | None = None,
    ) -> None:
        """Persist an audit log entry safely without breaking callers on telemetry error."""
        ip_address, user_agent = self.extract_client_meta(request)
        try:
            entry = AuditLog(
                org_id=org_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=ip_address,
                user_agent=user_agent,
                status=status,
                details=details,
            )
            self.db.add(entry)
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Audit log persistence failed for {action}: {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass

    async def list_org_logs(self, org_id: uuid.UUID, limit: int = 100) -> list[AuditLog]:
        """Return recent security audit log events for a specific tenant organization."""
        safe_limit = min(max(1, limit), 500)
        stmt = (
            select(AuditLog)
            .where(AuditLog.org_id == org_id)
            .order_by(AuditLog.created_at.desc())
            .limit(safe_limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
