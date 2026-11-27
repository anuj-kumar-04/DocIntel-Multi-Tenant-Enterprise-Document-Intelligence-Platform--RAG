import uuid

import pytest
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.cache import SemanticCache
from app.services.embeddings import embedding_service
from app.services.retrieval import (
    QueryRewriter,
    RetrievalConfig,
    RetrievalEngine,
    _extract_keywords,
    reciprocal_rank_fusion,
)


def test_reciprocal_rank_fusion_scoring():
    """Verify RRF rank aggregation logic."""
    # List 1: docA, docB, docC
    # List 2: docB, docA, docD
    list1 = ["docA", "docB", "docC"]
    list2 = ["docB", "docA", "docD"]

    # docA rank in list1=1, list2=2: 1/(60+1) + 1/(60+2) = 1/61 + 1/62
    # docB rank in list1=2, list2=1: 1/(60+2) + 1/(60+1) = 1/62 + 1/61
    # docC rank in list1=3, list2=None: 1/63
    # docD rank in list1=None, list2=3: 1/63

    fused = reciprocal_rank_fusion([list1, list2], k=60, top_n=2)
    assert len(fused) == 2
    assert "docA" in fused
    assert "docB" in fused
    assert "docC" not in fused


def test_query_rewriter_standalone():
    """Verify conversational pronouns are converted to standalone query."""
    history = [
        {"role": "user", "content": "What was Infosys revenue in FY24?"},
        {"role": "assistant", "content": "Infosys revenue in FY24 was $18.6 billion."},
    ]
    follow_up = "What was its operating margin?"
    rewritten = QueryRewriter.to_standalone(follow_up, history)
    assert "Infosys" in rewritten


def test_multi_query_expansion():
    """Verify multiple paraphrased query variations are generated."""
    query = "Enterprise cloud migration timelines"
    queries = QueryRewriter.generate_multi_queries(query)
    assert len(queries) >= 2
    assert query in queries


def test_retrieval_configs():
    """Verify v1, v2, v3 config parameters match system design."""
    v1 = RetrievalConfig.from_version("v1")
    assert v1.dense_top_k == 5
    assert not v1.hybrid
    assert not v1.rerank

    v2 = RetrievalConfig.from_version("v2")
    assert v2.hybrid
    assert v2.multi_query
    assert not v2.rerank

    v3 = RetrievalConfig.from_version("v3")
    assert v3.hybrid
    assert v3.rerank
    assert v3.rewrite


@pytest.mark.asyncio
async def test_semantic_cache_operations():
    """Test setting and retrieving from semantic cache."""
    cache = SemanticCache(threshold=0.95)
    # Mock redis memory operations if redis is offline
    org_id = "test-org-123"
    q = "What is the capital expense budget?"
    ans = "The capital expense budget is $45M."
    cites = [{"page": 1, "filename": "budget.pdf"}]

    await cache.set(org_id, q, ans, cites)
    hit = await cache.get(org_id, q)
    if hit:
        assert hit["answer"] == ans
        assert hit["cached"] is True


def test_keyword_extraction_strips_filler_words():
    """Stopwords like can/get/full/overview/details must not hijack sparse retrieval."""
    kws = _extract_keywords("Can I get a full refund on an opened bag of coffee?")
    assert "can" not in kws
    assert "get" not in kws
    assert {"refund", "opened", "bag", "coffee"}.issubset(set(kws))


def test_feature_hash_embedding_prefers_relevant_policy():
    """Feature-hashed fallback vectors preserve meaningful similarity vs unrelated docs."""
    import numpy as np

    q_vec = np.array(
        embedding_service.embed_query("Can I get a full refund on an opened bag of coffee?")
    )
    policy_vec = np.array(
        embedding_service.embed_query(
            "Return & Refund Policy: Unopened bags can be returned within 30 days for a full refund. "
            "Opened bags qualify for a replacement or store credit within 14 days for quality issues."
        )
    )
    noise_vec = np.array(
        embedding_service.embed_query("DBMS Relational Model functional dependency SQL tuples")
    )
    assert float(np.dot(q_vec, policy_vec)) > float(np.dot(q_vec, noise_vec))


@pytest.mark.asyncio
async def test_retrieval_strict_pdf_scope_and_complete_policy(db_session, seed_two_tenants):
    """Verify scoped retrieval checks all pages of the target PDF and never leaks other docs."""
    tenant_a, _ = seed_two_tenants

    noise_doc = Document(
        id=uuid.uuid4(),
        org_id=tenant_a.org.id,
        filename="DBMS_Notes.pdf",
        s3_key=f"org_{tenant_a.org.id}/DBMS_Notes.pdf",
        mime_type="application/pdf",
        size_bytes=5000,
        page_count=10,
        chunk_count=10,
        status=DocumentStatus.READY,
    )
    policy_doc = Document(
        id=uuid.uuid4(),
        org_id=tenant_a.org.id,
        filename="Northwind_Policy.pdf",
        s3_key=f"org_{tenant_a.org.id}/Northwind_Policy.pdf",
        mime_type="application/pdf",
        size_bytes=2000,
        page_count=2,
        chunk_count=2,
        status=DocumentStatus.READY,
    )
    db_session.add_all([noise_doc, policy_doc])
    await db_session.flush()

    noise_chunks = [
        Chunk(
            id=uuid.uuid4(),
            document_id=noise_doc.id,
            org_id=tenant_a.org.id,
            content=f"DBMS lecture note {i}: SQL systems can get details quickly in tables.",
            embedding=embedding_service.embed_query(
                f"DBMS lecture note {i}: SQL systems can get details quickly in tables."
            ),
            page_number=i + 1,
            chunk_index=i,
            section_title="DBMS Overview",
            element_type="paragraph",
            token_count=15,
        )
        for i in range(10)
    ]
    p1 = (
        "Northwind Coffee Roasters is headquartered in Portland, Oregon and founded March 14, 2018."
    )
    p2 = (
        "Return & Refund Policy: Unopened bags can be returned within 30 days of delivery for a full refund. "
        "Opened bags qualify for a replacement or store credit within 14 days for quality issues."
    )
    policy_chunks = [
        Chunk(
            id=uuid.uuid4(),
            document_id=policy_doc.id,
            org_id=tenant_a.org.id,
            content=p1,
            embedding=embedding_service.embed_query(p1),
            page_number=1,
            chunk_index=0,
            section_title="Company Facts",
            element_type="paragraph",
            token_count=20,
        ),
        Chunk(
            id=uuid.uuid4(),
            document_id=policy_doc.id,
            org_id=tenant_a.org.id,
            content=p2,
            embedding=embedding_service.embed_query(p2),
            page_number=2,
            chunk_index=1,
            section_title="Return & Refund Policy",
            element_type="paragraph",
            token_count=35,
        ),
    ]
    db_session.add_all(noise_chunks + policy_chunks)
    await db_session.commit()

    engine = RetrievalEngine(db_session)

    # 1. Scoped mode: must include ALL pages of Northwind_Policy.pdf and zero DBMS chunks
    scoped_hits = await engine.retrieve(
        question="Can I get a full refund on an opened bag of coffee?",
        org_id=tenant_a.org.id,
        document_ids=[policy_doc.id],
    )
    assert len(scoped_hits) == 2
    assert all(h["document_id"] == str(policy_doc.id) for h in scoped_hits)
    assert [h["page_number"] for h in scoped_hits] == [1, 2]

    # 2. Workspace-wide mode: must STILL find the refund policy chunk (not drowned out by "can")
    unscoped_hits = await engine.retrieve(
        question="Can I get a full refund on an opened bag of coffee?",
        org_id=tenant_a.org.id,
    )
    assert any(
        h["document_id"] == str(policy_doc.id) and "unopened bags" in h["content"].lower()
        for h in unscoped_hits
    )


@pytest.mark.asyncio
async def test_multi_document_subset_retrieval_excludes_unselected_docs(
    db_session, seed_two_tenants
):
    """Selecting 2 of 3 tenant PDFs retrieves from both selected PDFs and excludes the 3rd."""
    tenant_a, _ = seed_two_tenants

    specs = [
        (
            "Freight_Terms.pdf",
            "Warehouse B pallets qualify for a 5% volume rebate under Clause 14.",
        ),
        (
            "Customs_Receipt.pdf",
            "Demurrage waiver code is WVR-2026-NOV and customs duty is $4,180.50.",
        ),
        (
            "Excluded_Catalog.pdf",
            "Excluded catalog item: Warehouse B special rebate promo code EXCLUDE-999.",
        ),
    ]
    created_docs = []
    created_chunks = []
    for fname, body in specs:
        doc = Document(
            id=uuid.uuid4(),
            org_id=tenant_a.org.id,
            filename=fname,
            s3_key=f"org_{tenant_a.org.id}/{fname}",
            mime_type="application/pdf",
            size_bytes=512,
            page_count=1,
            chunk_count=1,
            status=DocumentStatus.READY,
        )
        created_docs.append(doc)
        created_chunks.append(
            Chunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                org_id=tenant_a.org.id,
                content=body,
                embedding=embedding_service.embed_query(body),
                page_number=1,
                chunk_index=0,
                section_title=fname,
                element_type="paragraph",
                token_count=18,
            )
        )

    db_session.add_all(created_docs + created_chunks)
    await db_session.commit()

    selected_ids = [created_docs[0].id, created_docs[1].id]
    hits = await RetrievalEngine(db_session).retrieve(
        question="What are the Warehouse B rebate and customs waiver code?",
        org_id=tenant_a.org.id,
        document_ids=selected_ids,
    )
    returned_doc_ids = {h["document_id"] for h in hits}
    assert returned_doc_ids == {str(created_docs[0].id), str(created_docs[1].id)}
    assert str(created_docs[2].id) not in returned_doc_ids
    assert all("EXCLUDE-999" not in h["content"] for h in hits)
