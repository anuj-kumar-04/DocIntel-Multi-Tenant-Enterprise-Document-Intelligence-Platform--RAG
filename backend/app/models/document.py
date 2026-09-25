from datetime import datetime
import enum
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.org import Organization
    from app.models.user import User
    from app.models.chunk import Chunk


class DocumentStatus(str, enum.Enum):
    QUEUED = "queued"
    PARSING = "parsing"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        SQLEnum(DocumentStatus, name="document_status", native_enum=False),
        default=DocumentStatus.QUEUED,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="documents")
    uploader: Mapped["User | None"] = relationship("User", back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_documents_org_status", "org_id", "status"),
        Index("ix_documents_org_hash", "org_id", "content_hash"),
    )
