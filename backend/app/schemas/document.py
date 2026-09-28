import uuid
from datetime import datetime

from app.models.document import DocumentStatus
from pydantic import BaseModel, ConfigDict


class DocumentUploadResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    status: DocumentStatus
    message: str
    is_duplicate: bool = False


class DocumentStatusResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    status: DocumentStatus
    chunk_count: int
    page_count: int
    error_message: str | None = None
    processed_at: datetime | None = None


class DocumentListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    page_count: int
    chunk_count: int
    status: DocumentStatus
    error_message: str | None = None
    created_at: datetime
    processed_at: datetime | None = None


class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    page_number: int
    chunk_index: int
    section_title: str | None = None
    element_type: str
    token_count: int
    content: str


class DocumentDetailResponse(DocumentListItemResponse):
    chunks: list[ChunkResponse] = []
