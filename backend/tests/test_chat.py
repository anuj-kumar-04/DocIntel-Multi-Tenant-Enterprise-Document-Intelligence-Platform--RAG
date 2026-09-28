import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import Organization


@pytest.mark.asyncio
async def test_conversation_lifecycle(client: AsyncClient, seed_two_tenants):
    """Test creating, listing, and retrieving conversations."""
    tenant_a, _ = seed_two_tenants

    # 1. Create conversation
    res = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Q4 Strategy"},
        headers=tenant_a.owner_headers,
    )
    assert res.status_code == 201
    conv_id = res.json()["id"]

    # 2. List conversations
    list_res = await client.get("/api/v1/chat/conversations", headers=tenant_a.owner_headers)
    assert list_res.status_code == 200
    assert any(c["id"] == conv_id for c in list_res.json())

    # 3. Get single conversation
    get_res = await client.get(
        f"/api/v1/chat/conversations/{conv_id}", headers=tenant_a.owner_headers
    )
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "Q4 Strategy"


@pytest.mark.asyncio
async def test_ask_stream_sse_events(client: AsyncClient, seed_two_tenants):
    """Test SSE streaming response emits valid event chunks."""
    tenant_a, _ = seed_two_tenants

    # Create conv
    conv_res = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Streaming Test"},
        headers=tenant_a.owner_headers,
    )
    conv_id = conv_res.json()["id"]

    # Ask
    res = await client.post(
        f"/api/v1/chat/conversations/{conv_id}/ask",
        json={"question": "What is our company policy?"},
        headers=tenant_a.owner_headers,
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    body = res.text
    assert "event: token" in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_token_budget_quota_enforcement(
    client: AsyncClient, db_session: AsyncSession, seed_two_tenants
):
    """Verify that exceeding monthly token budget immediately blocks queries with 429."""
    tenant_a, _ = seed_two_tenants

    # Artificially exhaust tenant A's budget
    org = await db_session.get(Organization, tenant_a.org.id)
    org.tokens_used_this_month = org.monthly_token_budget + 100
    await db_session.commit()

    conv_res = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Budget Block Test"},
        headers=tenant_a.owner_headers,
    )
    conv_id = conv_res.json()["id"]

    res = await client.post(
        f"/api/v1/chat/conversations/{conv_id}/ask",
        json={"question": "Hello?"},
        headers=tenant_a.owner_headers,
    )
    assert res.status_code == 429
    assert "budget" in res.json()["error"]["message"].lower()
