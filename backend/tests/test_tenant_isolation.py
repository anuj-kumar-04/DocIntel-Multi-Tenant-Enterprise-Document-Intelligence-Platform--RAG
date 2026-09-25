import json
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.embeddings import embedding_service


@pytest.mark.asyncio
async def test_strict_multi_tenant_isolation(
    client: AsyncClient, db_session: AsyncSession, seed_two_tenants
):
    """VERIFY ROW-LEVEL TENANT ISOLATION AT THE RETRIEVAL AND SQL LAYER.
    
    Org B possesses a proprietary document with confidential data ('Zephyrite quarterly margin').
    Org A must NEVER be able to retrieve, view, cite, or delete Org B's data under any circumstance.
    """
    tenant_a, tenant_b = seed_two_tenants

    # 1. Seed confidential document strictly in Org B
    doc_b = Document(
        id=uuid.uuid4(),
        org_id=tenant_b.org.id,
        filename="Zephyr_Internal_Margins_Q3.pdf",
        s3_key=f"org_{tenant_b.org.id}/Zephyr_Internal_Margins_Q3.pdf",
        mime_type="application/pdf",
        size_bytes=10240,
        page_count=1,
        chunk_count=1,
        status=DocumentStatus.READY,
    )
    db_session.add(doc_b)
    await db_session.flush()

    secret_content = (
        "CONFIDENTIAL — ZEPHYR INDUSTRIES INTERNAL MEMO: "
        "The proprietary Zephyrite quarterly margin for Q3 reached an unprecedented 47.8%."
    )
    chunk_b = Chunk(
        id=uuid.uuid4(),
        document_id=doc_b.id,
        org_id=tenant_b.org.id,  # Denormalized tenant key
        content=secret_content,
        embedding=embedding_service.embed_query(secret_content),
        page_number=1,
        chunk_index=0,
        section_title="Executive Margin Summary",
        element_type="paragraph",
        token_count=25,
    )
    db_session.add(chunk_b)
    await db_session.commit()

    # 2. Org A attempts to query Org B's secret data
    # Create conversation for Org A
    conv_res = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Espionage Attempt"},
        headers=tenant_a.owner_headers,
    )
    assert conv_res.status_code == 201
    conv_a_id = conv_res.json()["id"]

    # Org A asks for Zephyrite margin
    ask_res = await client.post(
        f"/api/v1/chat/conversations/{conv_a_id}/ask",
        json={"question": "What is the Zephyrite quarterly margin?"},
        headers=tenant_a.owner_headers,
    )
    assert ask_res.status_code == 200

    # Parse SSE stream
    body_text = ask_res.text
    assert "could not find this in the provided documents" in body_text.lower()
    
    # Assert zero citations returned to Org A
    assert '"citations": []' in body_text or '"citations":[]' in body_text

    # 3. Org A attempts direct access to Org B document -> 404
    get_doc_res = await client.get(
        f"/api/v1/documents/{doc_b.id}",
        headers=tenant_a.owner_headers,
    )
    assert get_doc_res.status_code == 404

    # 4. Org A attempts to delete Org B document -> 404
    del_doc_res = await client.delete(
        f"/api/v1/documents/{doc_b.id}",
        headers=tenant_a.owner_headers,
    )
    assert del_doc_res.status_code == 404

    # 5. Org A lists documents -> doc_b must not appear
    list_docs_res = await client.get(
        "/api/v1/documents",
        headers=tenant_a.owner_headers,
    )
    assert list_docs_res.status_code == 200
    listed_ids = [d["id"] for d in list_docs_res.json()]
    assert str(doc_b.id) not in listed_ids

    # 6. Verify Org B can legitimately ask and retrieve its own document
    conv_b_res = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Legitimate Internal Review"},
        headers=tenant_b.owner_headers,
    )
    assert conv_b_res.status_code == 201
    conv_b_id = conv_b_res.json()["id"]

    ask_b_res = await client.post(
        f"/api/v1/chat/conversations/{conv_b_id}/ask",
        json={"question": "What is the Zephyrite quarterly margin?"},
        headers=tenant_b.owner_headers,
    )
    assert ask_b_res.status_code == 200
    body_b = ask_b_res.text
    # Org B should receive its confidential answer and citations
    assert "47.8%" in body_b or "Zephyrite" in body_b
    assert "Zephyr_Internal_Margins_Q3.pdf" in body_b
