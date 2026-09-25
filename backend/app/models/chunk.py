from typing import TYPE_CHECKING
import uuid
from sqlalchemy import Computed, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.org import Organization


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Critical: org_id denormalized for zero-leak tenant isolation in single SQL query
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Generated TSVECTOR column for Postgres full-text / BM25 search
    content_tsv = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        nullable=True,
    )
    
    # pgvector embedding: 384 dimensions for BAAI/bge-small-en-v1.5
    embedding = mapped_column(Vector(384), nullable=True)

    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    element_type: Mapped[str] = mapped_column(String(64), nullable=False, default="paragraph")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_org_id", "org_id"),
        Index("ix_chunks_document_page", "document_id", "page_number"),
        Index("ix_chunks_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
