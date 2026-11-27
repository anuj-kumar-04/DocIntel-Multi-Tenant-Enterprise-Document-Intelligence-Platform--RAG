import uuid

import pytest
from app.models.document import Document, DocumentStatus
from app.models.org import Organization
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


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


@pytest.mark.asyncio
async def test_conversation_document_pinning_and_cross_tenant_block(
    client: AsyncClient, db_session: AsyncSession, seed_two_tenants
):
    """Verify PDF pinning persists on conversations and rejects cross-tenant document UUIDs."""
    tenant_a, tenant_b = seed_two_tenants

    doc_a = Document(
        id=uuid.uuid4(),
        org_id=tenant_a.org.id,
        filename="PolicyA.pdf",
        s3_key=f"org_{tenant_a.org.id}/PolicyA.pdf",
        mime_type="application/pdf",
        size_bytes=1200,
        page_count=1,
        chunk_count=0,
        status=DocumentStatus.READY,
    )
    doc_b = Document(
        id=uuid.uuid4(),
        org_id=tenant_b.org.id,
        filename="SecretB.pdf",
        s3_key=f"org_{tenant_b.org.id}/SecretB.pdf",
        mime_type="application/pdf",
        size_bytes=1200,
        page_count=1,
        chunk_count=0,
        status=DocumentStatus.READY,
    )
    db_session.add_all([doc_a, doc_b])
    await db_session.commit()

    # 1. Create session pinned to tenant A's PDF
    create_res = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Policy Session", "document_ids": [str(doc_a.id)]},
        headers=tenant_a.owner_headers,
    )
    assert create_res.status_code == 201
    conv = create_res.json()
    assert conv["document_ids"] == [str(doc_a.id)]

    # 2. Attempt to pin Tenant B's document UUID -> 404 (cross-tenant IDOR blocked)
    cross_patch = await client.patch(
        f"/api/v1/chat/conversations/{conv['id']}",
        json={"document_ids": [str(doc_b.id)]},
        headers=tenant_a.owner_headers,
    )
    assert cross_patch.status_code == 404

    cross_ask = await client.post(
        f"/api/v1/chat/conversations/{conv['id']}/ask",
        json={"question": "Summarize this", "document_ids": [str(doc_b.id)]},
        headers=tenant_a.owner_headers,
    )
    assert cross_ask.status_code == 404

    # 3. Clear pin back to workspace-wide
    clear_patch = await client.patch(
        f"/api/v1/chat/conversations/{conv['id']}",
        json={"document_ids": []},
        headers=tenant_a.owner_headers,
    )
    assert clear_patch.status_code == 200
    assert clear_patch.json()["document_ids"] is None


@pytest.mark.asyncio
async def test_multi_document_selection_persists_subset_and_rejects_partial_cross_tenant(
    client: AsyncClient, db_session: AsyncSession, seed_two_tenants
):
    """Selecting 2 of 3 tenant PDFs persists exact subset and blocks mixed cross-tenant lists."""
    tenant_a, tenant_b = seed_two_tenants

    docs_a = [
        Document(
            id=uuid.uuid4(),
            org_id=tenant_a.org.id,
            filename=f"Subset_{idx}.pdf",
            s3_key=f"org_{tenant_a.org.id}/Subset_{idx}.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            page_count=1,
            chunk_count=0,
            status=DocumentStatus.READY,
        )
        for idx in range(3)
    ]
    doc_b = Document(
        id=uuid.uuid4(),
        org_id=tenant_b.org.id,
        filename="OtherTenant.pdf",
        s3_key=f"org_{tenant_b.org.id}/OtherTenant.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        page_count=1,
        chunk_count=0,
        status=DocumentStatus.READY,
    )
    db_session.add_all([*docs_a, doc_b])
    await db_session.commit()

    subset_ids = [str(docs_a[0].id), str(docs_a[2].id)]
    res = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "2 PDFs: Subset_0", "document_ids": subset_ids},
        headers=tenant_a.owner_headers,
    )
    assert res.status_code == 201
    conv = res.json()
    assert conv["document_ids"] == subset_ids

    # Update scope to all 3, then back to 2 selected
    patch_three = await client.patch(
        f"/api/v1/chat/conversations/{conv['id']}",
        json={"document_ids": [str(d.id) for d in docs_a]},
        headers=tenant_a.owner_headers,
    )
    assert patch_three.status_code == 200
    assert len(patch_three.json()["document_ids"]) == 3

    # Reject mixed list containing another tenant's document
    mixed_patch = await client.patch(
        f"/api/v1/chat/conversations/{conv['id']}",
        json={"document_ids": [str(docs_a[0].id), str(doc_b.id)]},
        headers=tenant_a.owner_headers,
    )
    assert mixed_patch.status_code == 404
