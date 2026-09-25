from app.services.generation import (
    REFUSAL_MESSAGE,
    build_context_block,
    verify_and_clean_citations,
)


def test_build_context_block_formatting():
    """Verify context formatting includes index, filename, and page numbers."""
    chunks = [
        {"id": "c1", "document_id": "d1", "filename": "annual_report.pdf", "page_number": 14, "content": "Operating margin 28%."},
        {"id": "c2", "document_id": "d1", "filename": "annual_report.pdf", "page_number": 15, "content": "R&D expense $3.2B."},
    ]
    context_str, indexed_sources = build_context_block(chunks)

    assert "[1] (annual_report.pdf, p.14)" in context_str
    assert "[2] (annual_report.pdf, p.15)" in context_str
    assert len(indexed_sources) == 2
    assert indexed_sources[0]["index"] == 1
    assert indexed_sources[0]["page"] == 14


def test_verify_and_clean_citations_valid():
    """Verify that cited valid index is attached to metadata."""
    sources = [
        {"index": 1, "chunk_id": "c1", "document_id": "d1", "filename": "report.pdf", "page": 4, "snippet": "Text"},
        {"index": 2, "chunk_id": "c2", "document_id": "d1", "filename": "report.pdf", "page": 5, "snippet": "Text 2"},
    ]
    raw_answer = "The operating margin increased by 4% in Q3 [1]."
    cleaned, citations = verify_and_clean_citations(raw_answer, sources)

    assert "[1]" in cleaned
    assert len(citations) == 1
    assert citations[0]["index"] == 1
    assert citations[0]["page"] == 4


def test_verify_and_clean_citations_purges_hallucinated_indices():
    """Verify that hallucinated citation indices (e.g. [99]) are stripped."""
    sources = [
        {"index": 1, "chunk_id": "c1", "document_id": "d1", "filename": "report.pdf", "page": 4, "snippet": "Text"},
    ]
    # The LLM hallucinated source [99] which was never provided in context
    raw_answer = "Revenue was $10B [1] and net income was $2B [99]."
    cleaned, citations = verify_and_clean_citations(raw_answer, sources)

    assert "[1]" in cleaned
    assert "[99]" not in cleaned  # Stripped!
    assert len(citations) == 1
    assert citations[0]["index"] == 1


def test_refusal_cleans_any_citations():
    """Refusal responses must never carry citations."""
    sources = [
        {"index": 1, "chunk_id": "c1", "document_id": "d1", "filename": "report.pdf", "page": 4, "snippet": "Text"},
    ]
    raw_answer = f"{REFUSAL_MESSAGE} [1]"
    cleaned, citations = verify_and_clean_citations(raw_answer, sources)

    assert "[1]" not in cleaned
    assert citations == []
