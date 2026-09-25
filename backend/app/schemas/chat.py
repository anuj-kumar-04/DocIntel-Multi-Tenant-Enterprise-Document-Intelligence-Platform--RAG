from datetime import datetime
from typing import Any
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.models.chat import MessageRole


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="New Conversation", max_length=255)


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
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = []


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000)
    version: str | None = Field(default=None, description="Optional override: v1, v2, or v3")
