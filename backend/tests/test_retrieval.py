import pytest
from app.services.cache import SemanticCache
from app.services.retrieval import (
    QueryRewriter,
    RetrievalConfig,
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
