import uuid
from datetime import datetime
from typing import Any

from app.models.chat import MessageRole
from pydantic import BaseModel, ConfigDict, Field


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="New Conversation", max_length=255)
    document_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Optional document UUIDs strictly scoping this session to specific PDFs.",
    )


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    document_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Document UUIDs strictly scoping this session (empty list [] clears scope).",
    )


class CitationResponse(BaseModel):
    index: int
    chunk_id: str
    document_id: str
    filename: str
    page: int
    snippet: str


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    citations: list[dict[str, Any]] | None = None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int
    model: str | None = None
    created_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    user_id: uuid.UUID
    title: str
    document_ids: list[uuid.UUID] | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = []


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000)
    version: str | None = Field(default=None, description="Optional override: v1, v2, or v3")
    document_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Optional document UUIDs restricting answers strictly to those PDFs.",
    )
