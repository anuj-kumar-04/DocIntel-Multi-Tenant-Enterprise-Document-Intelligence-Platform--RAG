from collections.abc import AsyncGenerator
import json
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ResourceNotFoundError
from app.core.logging import logger
from app.core.tracing import TraceContext
from app.deps import get_current_user, get_db
from app.models.chat import Conversation, Message, MessageRole
from app.models.user import User
from app.schemas.chat import (
    AskRequest,
    ConversationCreateRequest,
    ConversationResponse,
    MessageResponse,
)
from app.services.budget import BudgetService
from app.services.cache import semantic_cache
from app.services.generation import generation_service
from app.services.retrieval import RetrievalConfig, RetrievalEngine

router = APIRouter(prefix="/chat", tags=["Chat & RAG"])


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    req: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversational session within tenant organization."""
    conv = Conversation(
        org_id=current_user.org_id,
        user_id=current_user.id,
        title=req.title,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return ConversationResponse(
        id=conv.id,
        org_id=conv.org_id,
        user_id=conv.user_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[],
    )


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all active conversations for the authenticated user."""
    stmt = (
        select(Conversation)
        .where(
            Conversation.org_id == current_user.org_id,
            Conversation.user_id == current_user.id,
        )
        .options(selectinload(Conversation.messages))
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(stmt)
    convs = result.scalars().all()
    return [
        ConversationResponse(
            id=c.id,
            org_id=c.org_id,
            user_id=c.user_id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
            messages=[
                MessageResponse.model_validate(m) for m in (c.messages or [])
            ],
        )
        for c in convs
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve conversation details and associated messages."""
    stmt = (
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.org_id == current_user.org_id,
        )
        .options(selectinload(Conversation.messages))
    )
    result = await db.execute(stmt)
    conv = result.scalars().first()
    if not conv:
        raise ResourceNotFoundError("Conversation", str(conversation_id))
    return ConversationResponse(
        id=conv.id,
        org_id=conv.org_id,
        user_id=conv.user_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[
            MessageResponse.model_validate(m) for m in (conv.messages or [])
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation and its messages."""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.org_id == current_user.org_id,
    )
    result = await db.execute(stmt)
    conv = result.scalars().first()
    if not conv:
        raise ResourceNotFoundError("Conversation", str(conversation_id))

    await db.delete(conv)
    await db.commit()
    return None


@router.post("/conversations/{conversation_id}/ask")
async def ask_question_stream(
    conversation_id: uuid.UUID,
    req: AskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events (SSE) streaming chat endpoint with strict grounding and citations."""
    # 1. Enforce monthly token budget before processing
    budget_svc = BudgetService(db)
    await budget_svc.assert_within_limit(current_user.org_id)

    # 2. Verify conversation ownership
    stmt = (
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.org_id == current_user.org_id,
        )
        .options(selectinload(Conversation.messages))
    )
    result = await db.execute(stmt)
    conv = result.scalars().first()
    if not conv:
        raise ResourceNotFoundError("Conversation", str(conversation_id))

    # 3. Persist user question
    user_msg = Message(
        conversation_id=conv.id,
        role=MessageRole.USER,
        content=req.question,
    )
    db.add(user_msg)
    await db.commit()

    # Format recent history
    history = [
        {"role": m.role.value, "content": m.content}
        for m in (conv.messages or [])[-6:]
    ]

    async def sse_event_generator() -> AsyncGenerator[str, None]:
        start_time = time.perf_counter()
        trace = TraceContext(
            name="rag_ask",
            user_id=str(current_user.id),
            org_id=str(current_user.org_id),
        )

        try:
            # 4. Semantic cache check
            cached_result = await semantic_cache.get(str(current_user.org_id), req.question)
            if cached_result:
                # Emit cached tokens
                answer_text = cached_result["answer"]
                citations = cached_result.get("citations", [])

                for char in answer_text:
                    yield f"event: token\ndata: {json.dumps({'token': char})}\n\n"

                yield f"event: citations\ndata: {json.dumps({'citations': citations})}\n\n"
                yield f"event: usage\ndata: {json.dumps({'prompt_tokens': 0, 'completion_tokens': 0, 'cost_usd': 0.0, 'cached': True})}\n\n"

                # Save assistant message
                assistant_msg = Message(
                    conversation_id=conv.id,
                    role=MessageRole.ASSISTANT,
                    content=answer_text,
                    citations=citations,
                    prompt_tokens=0,
                    completion_tokens=0,
                    cost_usd=0.0,
                    latency_ms=int((time.perf_counter() - start_time) * 1000),
                    model="semantic_cache",
                    trace_id=trace.trace_id,
                )
                db.add(assistant_msg)
                await db.commit()

                yield f"event: done\ndata: {json.dumps({'message_id': str(assistant_msg.id), 'status': 'completed'})}\n\n"
                return

            # 5. Hybrid Retrieval
            retrieval_cfg = (
                RetrievalConfig.from_version(req.version)
                if req.version
                else None
            )
            retrieval_engine = RetrievalEngine(db)

            async with trace.span("retrieval", {"version": req.version or "default"}):
                chunks = await retrieval_engine.retrieve(
                    question=req.question,
                    org_id=current_user.org_id,
                    history=history,
                    config=retrieval_cfg,
                )

            # 6. Generation & Citation stream
            collected_text = []
            final_citations = []
            usage_data = {}

            async with trace.span("generation"):
                async for event in generation_service.generate_stream(req.question, chunks, history):
                    event_type = event.get("type")
                    if event_type == "token":
                        collected_text.append(event["token"])
                        yield f"event: token\ndata: {json.dumps({'token': event['token']})}\n\n"
                    elif event_type == "citations":
                        final_citations = event["citations"]
                        yield f"event: citations\ndata: {json.dumps({'citations': final_citations})}\n\n"
                    elif event_type == "usage":
                        usage_data = event
                        yield f"event: usage\ndata: {json.dumps(usage_data)}\n\n"
                    elif event_type == "done":
                        pass

            full_answer = usage_data.get("full_answer", "".join(collected_text))
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            tokens = usage_data.get("prompt_tokens", 0) + usage_data.get("completion_tokens", 0)
            cost = usage_data.get("cost_usd", 0.0)
            model_used = usage_data.get("model", "unknown")

            # 7. Persist assistant message
            assistant_msg = Message(
                conversation_id=conv.id,
                role=MessageRole.ASSISTANT,
                content=full_answer,
                citations=final_citations,
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                cost_usd=cost,
                latency_ms=latency_ms,
                model=model_used,
                trace_id=trace.trace_id,
            )
            db.add(assistant_msg)
            await db.commit()
            await db.refresh(assistant_msg)

            # 8. Record token consumption & update cache
            await budget_svc.record_usage(
                org_id=current_user.org_id,
                user_id=current_user.id,
                tokens=tokens,
                cost_usd=cost,
                event_type="chat",
            )

            if "could not find this" not in full_answer.lower():
                await semantic_cache.set(
                    str(current_user.org_id),
                    req.question,
                    full_answer,
                    final_citations,
                )

            trace.log_generation(
                name="rag_answer",
                model=model_used,
                input_messages=req.question,
                output=full_answer,
                usage={"total_tokens": tokens},
                cost=cost,
            )

            yield f"event: done\ndata: {json.dumps({'message_id': str(assistant_msg.id), 'status': 'completed'})}\n\n"

        except Exception as e:
            logger.exception("Streaming generation error")
            err_payload = {"error": str(e)}
            yield f"event: error\ndata: {json.dumps(err_payload)}\n\n"

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
