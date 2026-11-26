import json
import time
import uuid
from collections.abc import AsyncGenerator

from app.core.errors import ResourceNotFoundError
from app.core.logging import logger
from app.core.rate_limit import limiter
from app.core.tracing import TraceContext
from app.deps import get_current_user, get_db
from app.models.chat import Conversation, Message, MessageRole
from app.models.document import Document
from app.models.user import User
from app.schemas.chat import (
    AskRequest,
    ConversationCreateRequest,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageResponse,
)
from app.services.budget import BudgetService
from app.services.cache import semantic_cache
from app.services.generation import generation_service
from app.services.guardrails import detect_prompt_injection
from app.services.retrieval import RetrievalConfig, RetrievalEngine
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/chat", tags=["Chat & RAG"])


async def _validate_scoped_documents(
    db: AsyncSession, org_id: uuid.UUID, doc_ids: list[uuid.UUID] | None
) -> list[uuid.UUID] | None:
    """Validate that all requested document UUIDs exist and belong strictly to the caller's org."""
    if not doc_ids:
        return None
    unique_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for did in doc_ids:
        if did not in seen:
            seen.add(did)
            unique_ids.append(did)

    stmt = select(Document.id).where(Document.org_id == org_id, Document.id.in_(unique_ids))
    rows = await db.execute(stmt)
    found_ids = {r[0] for r in rows.fetchall()}
    missing = [str(did) for did in unique_ids if did not in found_ids]
    if missing:
        raise ResourceNotFoundError("Document", missing[0])
    return unique_ids


def _parse_conv_doc_ids(raw_ids: list[str] | None) -> list[uuid.UUID] | None:
    if not raw_ids:
        return None
    parsed: list[uuid.UUID] = []
    for item in raw_ids:
        try:
            parsed.append(uuid.UUID(str(item)))
        except ValueError:
            continue
    return parsed or None


@router.post(
    "/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED
)
async def create_conversation(
    req: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversational session within tenant organization."""
    valid_doc_ids = await _validate_scoped_documents(db, current_user.org_id, req.document_ids)
    conv = Conversation(
        org_id=current_user.org_id,
        user_id=current_user.id,
        title=req.title,
        document_ids=[str(d) for d in valid_doc_ids] if valid_doc_ids else None,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return ConversationResponse(
        id=conv.id,
        org_id=conv.org_id,
        user_id=conv.user_id,
        title=conv.title,
        document_ids=valid_doc_ids,
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
            document_ids=_parse_conv_doc_ids(c.document_ids),
            created_at=c.created_at,
            updated_at=c.updated_at,
            messages=[MessageResponse.model_validate(m) for m in (c.messages or [])],
        )
        for c in convs
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve conversation details and associated messages (strict user & tenant scope)."""
    stmt = (
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.org_id == current_user.org_id,
            Conversation.user_id == current_user.id,
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
        document_ids=_parse_conv_doc_ids(conv.document_ids),
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[MessageResponse.model_validate(m) for m in (conv.messages or [])],
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: uuid.UUID,
    req: ConversationUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update conversation title or strictly pin/unpin scoped document UUIDs."""
    stmt = (
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.org_id == current_user.org_id,
            Conversation.user_id == current_user.id,
        )
        .options(selectinload(Conversation.messages))
    )
    result = await db.execute(stmt)
    conv = result.scalars().first()
    if not conv:
        raise ResourceNotFoundError("Conversation", str(conversation_id))

    if req.title is not None:
        conv.title = req.title
    if req.document_ids is not None:
        if len(req.document_ids) == 0:
            conv.document_ids = None
        else:
            valid_doc_ids = await _validate_scoped_documents(
                db, current_user.org_id, req.document_ids
            )
            conv.document_ids = [str(d) for d in valid_doc_ids] if valid_doc_ids else None

    await db.commit()
    await db.refresh(conv)
    return ConversationResponse(
        id=conv.id,
        org_id=conv.org_id,
        user_id=conv.user_id,
        title=conv.title,
        document_ids=_parse_conv_doc_ids(conv.document_ids),
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[MessageResponse.model_validate(m) for m in (conv.messages or [])],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation and its messages (strict user & tenant scope)."""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.org_id == current_user.org_id,
        Conversation.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    conv = result.scalars().first()
    if not conv:
        raise ResourceNotFoundError("Conversation", str(conversation_id))

    await db.delete(conv)
    await db.commit()
    return None


@router.post("/conversations/{conversation_id}/ask")
@limiter.limit("30/minute")
async def ask_question_stream(
    request: Request,
    conversation_id: uuid.UUID,
    req: AskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events (SSE) streaming chat endpoint with strict grounding and citations."""
    # 0. Guard against prompt-injection overrides
    if detect_prompt_injection(req.question):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query rejected by security policy.",
        )

    # 1. Enforce monthly token budget before processing
    budget_svc = BudgetService(db)
    await budget_svc.assert_within_limit(current_user.org_id)

    # 2. Verify conversation ownership (strict tenant & user scope)
    stmt = (
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.org_id == current_user.org_id,
            Conversation.user_id == current_user.id,
        )
        .options(selectinload(Conversation.messages))
    )
    result = await db.execute(stmt)
    conv = result.scalars().first()
    if not conv:
        raise ResourceNotFoundError("Conversation", str(conversation_id))

    # 2b. Resolve & validate strict document scope (request overrides conversation pin when provided)
    if req.document_ids is not None:
        if len(req.document_ids) == 0:
            scoped_doc_ids = None
        else:
            scoped_doc_ids = await _validate_scoped_documents(
                db, current_user.org_id, req.document_ids
            )
    else:
        raw_conv_docs = _parse_conv_doc_ids(conv.document_ids)
        if raw_conv_docs:
            # Keep only docs that still exist in org (in case one was deleted)
            stmt_docs = select(Document.id).where(
                Document.org_id == current_user.org_id,
                Document.id.in_(raw_conv_docs),
            )
            found_rows = await db.execute(stmt_docs)
            valid_set = {r[0] for r in found_rows.fetchall()}
            scoped_doc_ids = [d for d in raw_conv_docs if d in valid_set] or None
        else:
            scoped_doc_ids = None

    cache_scope = ",".join(sorted(str(d) for d in scoped_doc_ids)) if scoped_doc_ids else "all"

    # 3. Persist user question
    user_msg = Message(
        conversation_id=conv.id,
        role=MessageRole.USER,
        content=req.question,
    )
    db.add(user_msg)
    await db.commit()

    # Format recent history
    history = [{"role": m.role.value, "content": m.content} for m in (conv.messages or [])[-6:]]

    async def sse_event_generator() -> AsyncGenerator[str, None]:
        start_time = time.perf_counter()
        trace = TraceContext(
            name="rag_conversation_ask",
            user_id=str(current_user.id),
            session_id=str(conversation_id),
            org_id=str(current_user.org_id),
            tags=["rag", "production", f"retrieval:{req.version or 'v3'}"],
            input_data={"question": req.question, "conversation_id": str(conversation_id)},
            metadata={
                "retrieval_version": req.version or "v3",
                "user_email": current_user.email,
                "document_scope": cache_scope,
            },
        )

        async with trace.start_root():
            try:
                # 4. Semantic cache check (strictly scoped by org + selected PDFs)
                cached_result = None
                async with trace.cache_step(
                    name="semantic_cache_lookup",
                    input_data={"question": req.question, "scope": cache_scope},
                ) as cache_obs:
                    cached_result = await semantic_cache.get(
                        str(current_user.org_id), req.question, scope=cache_scope
                    )
                    if cache_obs:
                        cache_obs.update(output={"hit": bool(cached_result)})

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

                    trace.set_output(
                        {"answer": answer_text, "citations": citations, "cached": True}
                    )
                    yield f"event: done\ndata: {json.dumps({'message_id': str(assistant_msg.id), 'status': 'completed'})}\n\n"
                    return

                # 5. Hybrid Retrieval
                retrieval_cfg = RetrievalConfig.from_version(req.version) if req.version else None
                retrieval_engine = RetrievalEngine(db)

                async with trace.retriever_step(
                    name="hybrid_retrieval",
                    input_data={
                        "question": req.question,
                        "version": req.version or "v3",
                        "org_id": str(current_user.org_id),
                    },
                ) as ret_obs:
                    chunks = await retrieval_engine.retrieve(
                        question=req.question,
                        org_id=current_user.org_id,
                        history=history,
                        config=retrieval_cfg,
                        document_ids=scoped_doc_ids,
                    )
                    if ret_obs:
                        ret_obs.update(
                            output={
                                "retrieved_count": len(chunks),
                                "chunks": [
                                    {
                                        "id": c.get("id"),
                                        "document": c.get("filename"),
                                        "page": c.get("page_number"),
                                        "score": c.get("score"),
                                        "section": c.get("section_title"),
                                    }
                                    for c in chunks
                                ],
                            }
                        )

                # 6. Generation & Citation stream
                collected_text = []
                final_citations = []
                usage_data = {}

                async for event in generation_service.generate_stream(
                    req.question, chunks, history
                ):
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
                prompt_tokens = usage_data.get("prompt_tokens", 0)
                completion_tokens = usage_data.get("completion_tokens", 0)
                tokens = prompt_tokens + completion_tokens
                cost = usage_data.get("cost_usd", 0.0)
                model_used = usage_data.get("model", "unknown")

                # 7. Persist assistant message
                assistant_msg = Message(
                    conversation_id=conv.id,
                    role=MessageRole.ASSISTANT,
                    content=full_answer,
                    citations=final_citations,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
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
                        scope=cache_scope,
                    )

                trace.log_generation(
                    name="llm_generation",
                    model=model_used,
                    input_messages=[
                        {
                            "role": "system",
                            "content": "You are DocIntel, an enterprise document intelligence assistant.",
                        },
                        {"role": "user", "content": req.question},
                    ],
                    output=full_answer,
                    usage={
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": tokens,
                    },
                    cost=cost,
                    metadata={"citations_count": len(final_citations)},
                )

                trace.set_output(
                    {
                        "answer": full_answer,
                        "citations": final_citations,
                        "model": model_used,
                        "total_tokens": tokens,
                        "cost_usd": cost,
                    }
                )

                yield f"event: done\ndata: {json.dumps({'message_id': str(assistant_msg.id), 'status': 'completed'})}\n\n"

            except Exception as e:
                logger.exception("Streaming generation error")
                err_payload = {"error": "An internal error occurred while generating the response."}
                trace.set_output({"error": str(e)})
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
