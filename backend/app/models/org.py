import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.chat import Conversation
    from app.models.document import Document
    from app.models.usage import UsageEvent
    from app.models.user import User


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="enterprise", nullable=False)
    monthly_token_budget: Mapped[int] = mapped_column(BigInteger, default=1_000_000, nullable=False)
    tokens_used_this_month: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Relationships
    users: Mapped[list["User"]] = relationship(
        "User", back_populates="organization", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="organization", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="organization", cascade="all, delete-orphan"
    )
    usage_events: Mapped[list["UsageEvent"]] = relationship(
        "UsageEvent", back_populates="organization", cascade="all, delete-orphan"
    )
