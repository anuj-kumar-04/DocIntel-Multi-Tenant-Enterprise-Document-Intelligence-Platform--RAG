import io
import uuid

import fitz
import numpy as np
import pytest
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.chunking import LayoutChunker
from app.services.embeddings import embedding_service
from app.services.parsing import DocumentParser, ParsedBlock
from app.services.retrieval import RetrievalEngine
from httpx import AsyncClient
from PIL import Image, ImageDraw, ImageFont


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
        ParsedBlock(
            content="Financial highlights for Q1.", page_number=1, element_type="paragraph"
        ),
        ParsedBlock(
            content="| Metric | Q1 | Q2 |\n| --- | --- | --- |\n| Revenue | $10M | $12M |",
            page_number=2,
            element_type="table",
            section_title="Performance Table",
        ),
        ParsedBlock(
            content="Subsequent operational notes.", page_number=3, element_type="paragraph"
        ),
    ]

    chunks = chunker.chunk_blocks(blocks)
    assert len(chunks) >= 3

    # Check table chunk
    table_chunk = next(c for c in chunks if c.element_type == "table")
    assert table_chunk.page_number == 2
    assert "Revenue" in table_chunk.content
    assert table_chunk.section_title == "Performance Table"


def _render_synthetic_scan_png(
    lines: list[str],
    rotate_deg: float = 0.0,
    add_noise: bool = False,
) -> bytes:
    """Create a realistic scanned image with optional skew and impulse noise."""
    img = Image.new("RGB", (1400, 600), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=42)
    except TypeError:
        font = ImageFont.load_default()

    y = 70
    for line in lines:
        draw.text((70, y), line, fill="black", font=font)
        y += 95

    if add_noise:
        rng = np.random.default_rng(42)
        arr = np.array(img, dtype=np.int16)
        speckle = rng.random(arr.shape[:2]) < 0.012
        arr[speckle] = 85
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    if rotate_deg:
        img = img.rotate(rotate_deg, expand=True, fillcolor="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_scanned_pdf_rotated_noisy_ocr_extraction():
    """Low-text scanned pages (including noisy rotated scans) extract via high-DPI OCR."""
    scan_png = _render_synthetic_scan_png(
        [
            "APPENDIX B TRAVEL POLICY",
            "Maximum hotel limit is 275 USD per night.",
            "Receipts required within 14 days.",
        ],
        rotate_deg=5.0,
        add_noise=True,
    )

    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text(
        (72, 72),
        "Corporate Travel Policy Overview: Standard reimbursement applies to pre-approved trips.",
    )
    p2 = doc.new_page()
    p2.insert_image(fitz.Rect(36, 72, 560, 360), stream=scan_png)
    pdf_bytes = doc.tobytes()
    doc.close()

    blocks, page_count = DocumentParser.parse_pdf(pdf_bytes)
    assert page_count == 2

    chunks = LayoutChunker(target_chunk_size=700, chunk_overlap=100).chunk_blocks(blocks)
    p1_text = " ".join(c.content for c in chunks if c.page_number == 1)
    p2_text = " ".join(c.content for c in chunks if c.page_number == 2)

    assert "pre-approved trips" in p1_text
    assert "275" in p2_text
    assert "hotel" in p2_text.lower()


def test_hybrid_pdf_page_merges_native_and_embedded_image_ocr():
    """Pages with native text + embedded raster images extract and merge both into page chunks."""
    receipt_png = _render_synthetic_scan_png(
        [
            "VENDOR BLUEBIRD LOGISTICS",
            "TOTAL AMOUNT 418.50 USD",
        ]
    )

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Expense Policy Section 4: Approved freight carrier invoices and signed receipts are archived below.",
    )
    page.insert_image(fitz.Rect(72, 160, 520, 360), stream=receipt_png)
    pdf_bytes = doc.tobytes()
    doc.close()

    blocks, page_count = DocumentParser.parse_pdf(pdf_bytes)
    assert page_count == 1

    chunks = LayoutChunker(target_chunk_size=700, chunk_overlap=100).chunk_blocks(blocks)
    assert len(chunks) >= 1
    combined_p1 = " ".join(c.content for c in chunks if c.page_number == 1)
    assert "Approved freight carrier" in combined_p1
    assert "418.50" in combined_p1
    assert "bluebird" in combined_p1.lower()


@pytest.mark.asyncio
async def test_scanned_pdf_chunks_searchable_via_hybrid_retrieval(db_session, seed_two_tenants):
    """OCR-extracted scanned appendix chunks are retrievable by both BM25 and vector search."""
    tenant_a, _ = seed_two_tenants

    scan_png = _render_synthetic_scan_png(
        [
            "SCANNED APPENDIX C REFUND",
            "Damaged glassware refund window is 21 days.",
        ]
    )
    doc_pdf = fitz.open()
    p1 = doc_pdf.new_page()
    p1.insert_text(
        (72, 72),
        "General Storefront Terms: Normal unopened merchandise may be returned cleanly.",
    )
    p2 = doc_pdf.new_page()
    p2.insert_image(fitz.Rect(36, 72, 560, 340), stream=scan_png)
    pdf_bytes = doc_pdf.tobytes()
    doc_pdf.close()

    blocks, page_count = DocumentParser.parse_pdf(pdf_bytes)
    chunk_records = LayoutChunker(target_chunk_size=700, chunk_overlap=100).chunk_blocks(blocks)
    vectors = embedding_service.embed_documents([c.content for c in chunk_records])

    doc_row = Document(
        id=uuid.uuid4(),
        org_id=tenant_a.org.id,
        filename="Policy_With_Scanned_Appendix.pdf",
        s3_key=f"org_{tenant_a.org.id}/Policy_With_Scanned_Appendix.pdf",
        mime_type="application/pdf",
        size_bytes=len(pdf_bytes),
        page_count=page_count,
        chunk_count=len(chunk_records),
        status=DocumentStatus.READY,
    )
    db_session.add(doc_row)
    await db_session.flush()

    db_chunks = [
        Chunk(
            document_id=doc_row.id,
            org_id=tenant_a.org.id,
            content=c.content,
            embedding=emb,
            page_number=c.page_number,
            chunk_index=c.chunk_index,
            section_title=c.section_title,
            element_type=c.element_type,
            token_count=c.token_count,
        )
        for c, emb in zip(chunk_records, vectors, strict=False)
    ]
    db_session.add_all(db_chunks)
    await db_session.commit()

    hits = await RetrievalEngine(db_session).retrieve(
        question="What is the damaged glassware refund window in Appendix C?",
        org_id=tenant_a.org.id,
        document_ids=[doc_row.id],
    )
    assert any(h["page_number"] == 2 and "21" in h["content"] for h in hits)
