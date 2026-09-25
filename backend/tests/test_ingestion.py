import io
import pytest
from httpx import AsyncClient

from app.services.chunking import LayoutChunker
from app.services.parsing import ParsedBlock


@pytest.mark.asyncio
async def test_upload_document_success(client: AsyncClient, seed_two_tenants):
    """Test document upload enqueues ingestion and returns 202."""
    tenant_a, _ = seed_two_tenants
    file_content = b"Acme Fiscal Q4 summary: Total cloud revenue exceeded $6.2 billion."
    files = {"file": ("q4_summary.txt", io.BytesIO(file_content), "text/plain")}

    response = await client.post("/api/v1/documents", files=files, headers=tenant_a.owner_headers)
    assert response.status_code == 202
    data = response.json()
    assert "document_id" in data
    assert data["filename"] == "q4_summary.txt"
    assert data["status"] in ["queued", "ready"]


@pytest.mark.asyncio
async def test_upload_empty_file_rejected(client: AsyncClient, seed_two_tenants):
    """Uploading an empty 0-byte file returns 400 Bad Request."""
    tenant_a, _ = seed_two_tenants
    files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}

    response = await client.post("/api/v1/documents", files=files, headers=tenant_a.owner_headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_idempotent_document_upload(client: AsyncClient, seed_two_tenants):
    """Re-uploading the exact same file in same org returns existing document."""
    tenant_a, _ = seed_two_tenants
    file_bytes = b"Static policy documentation content for idempotency check."

    # 1. First upload
    f1 = {"file": ("policy.txt", io.BytesIO(file_bytes), "text/plain")}
    res1 = await client.post("/api/v1/documents", files=f1, headers=tenant_a.owner_headers)
    doc_id_1 = res1.json()["document_id"]

    # 2. Second upload identical content
    f2 = {"file": ("policy.txt", io.BytesIO(file_bytes), "text/plain")}
    res2 = await client.post("/api/v1/documents", files=f2, headers=tenant_a.owner_headers)
    assert res2.status_code == 202 or res2.status_code == 200
    doc_id_2 = res2.json()["document_id"]

    assert doc_id_1 == doc_id_2


def test_chunker_preserves_table_and_page_metadata():
    """Verify that table elements are kept intact and page numbers preserved."""
    chunker = LayoutChunker(target_chunk_size=500, chunk_overlap=50)

    blocks = [
        ParsedBlock(content="Financial highlights for Q1.", page_number=1, element_type="paragraph"),
        ParsedBlock(
            content="| Metric | Q1 | Q2 |\n| --- | --- | --- |\n| Revenue | $10M | $12M |",
            page_number=2,
            element_type="table",
            section_title="Performance Table",
        ),
        ParsedBlock(content="Subsequent operational notes.", page_number=3, element_type="paragraph"),
    ]

    chunks = chunker.chunk_blocks(blocks)
    assert len(chunks) >= 3

    # Check table chunk
    table_chunk = next(c for c in chunks if c.element_type == "table")
    assert table_chunk.page_number == 2
    assert "Revenue" in table_chunk.content
    assert table_chunk.section_title == "Performance Table"
