import re
import uuid
from typing import Any

from app.config import settings
from app.core.logging import logger
from app.services.embeddings import embedding_service
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]], k: int = 60, top_n: int = 30
) -> list[str]:
    """Reciprocal Rank Fusion (RRF) algorithm to fuse diverse ranked ID lists.

    Formula: score(d) = sum(1 / (k + rank(d)))
    Independent of score distributions and scales.
    """
    scores: dict[str, float] = {}
    for lst in ranked_lists:
        for rank, doc_id in enumerate(lst, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return sorted_ids[:top_n]


class RetrievalConfig(BaseModel):
    version: str = "v3"
    rewrite: bool = True
    multi_query: bool = True
    hybrid: bool = True
    rerank: bool = True
    dense_top_k: int = 20
    sparse_top_k: int = 20
    fusion_top_n: int = 30
    final_k: int = 6

    @classmethod
    def from_version(cls, version: str) -> "RetrievalConfig":
        v = version.lower()
        if v == "v1":
            # v1: Naive dense-only baseline (top 5 straight to context)
            return cls(
                version="v1",
                rewrite=False,
                multi_query=False,
                hybrid=False,
                rerank=False,
                dense_top_k=5,
                final_k=5,
            )
        elif v == "v2":
            # v2: Hybrid dense + sparse BM25 + multi-query expansion + RRF
            return cls(
                version="v2",
                rewrite=False,
                multi_query=True,
                hybrid=True,
                rerank=False,
                dense_top_k=20,
                sparse_top_k=20,
                fusion_top_n=30,
                final_k=8,
            )
        else:
            # v3: Full enterprise stack (rewrite + multi-query + hybrid + cross-encoder rerank)
            return cls(
                version="v3",
                rewrite=True,
                multi_query=True,
                hybrid=True,
                rerank=True,
                dense_top_k=settings.DENSE_TOP_K,
                sparse_top_k=settings.SPARSE_TOP_K,
                fusion_top_n=settings.FUSION_TOP_N,
                final_k=settings.FINAL_RERANK_TOP_K,
            )


class CrossEncoderReranker:
    """Joint query-document cross-encoder re-ranking service."""

    def __init__(self):
        self._model = None
        self._initialized = False

    def _get_model(self):
        if not self._initialized:
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(settings.RERANKER_MODEL_NAME)
                logger.info(f"Loaded CrossEncoder: {settings.RERANKER_MODEL_NAME}")
            except Exception as e:
                logger.warning(f"CrossEncoder unavailable ({e}). Using lexical-density reranker.")
                self._model = None
            self._initialized = True
        return self._model

    def rank(
        self, query: str, candidates: list[dict[str, Any]], top_k: int = 6
    ) -> list[dict[str, Any]]:
        """Re-rank candidate chunks against the standalone query."""
        if not candidates:
            return []

        model = self._get_model()
        if model:
            try:
                pairs = []
                for c in candidates:
                    sec = re.sub(
                        r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", c.get("section_title") or ""
                    ).strip()
                    content = re.sub(
                        r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", c.get("content") or ""
                    ).strip()
                    doc_text = f"{sec}\n{content}" if sec else content
                    pairs.append([query, doc_text])
                scores = model.predict(pairs)
                for c, s in zip(candidates, scores, strict=False):
                    c["rerank_score"] = float(s)
                return sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)[:top_k]
            except Exception as e:
                logger.warning(f"Cross-encoder scoring error: {e}")

        # Fallback lexical and term frequency scoring
        clean_q = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", query).lower()
        q_words = set(re.findall(r"\w+", clean_q))
        for c in candidates:
            raw_text = c.get("content", "") + " " + (c.get("section_title") or "")
            clean_text = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", raw_text).lower()
            overlap = sum(1 for w in q_words if w in clean_text)
            density = overlap / (len(q_words) + 1e-5)
            # Boost table chunks slightly for structured queries
            type_boost = (
                1.3 if c.get("element_type") == "table" or "|" in c.get("content", "") else 1.0
            )
            # Boost if section title matches query terms
            title_boost = (
                1.3
                if c.get("section_title")
                and any(w in (c.get("section_title") or "").lower() for w in q_words)
                else 1.0
            )
            c["rerank_score"] = density * type_boost * title_boost

        return sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)[:top_k]


class QueryRewriter:
    """Conversational standalone query reformer and multi-query generator."""

    @staticmethod
    def to_standalone(question: str, history: list[dict[str, str]]) -> str:
        """Resolve pronouns and coreferences into a self-contained query."""
        if not history:
            return question

        # Extract last user query for topic context
        last_topics = []
        for msg in reversed(history[-4:]):
            if msg.get("role") == "user":
                last_topics.append(msg.get("content", ""))

        if not last_topics:
            return question

        q_lower = question.lower()
        pronouns = ["it", "its", "they", "their", "this", "that", "these", "those", "he", "she"]
        if any(re.search(rf"\b{p}\b", q_lower) for p in pronouns):
            # Synthesize contextually qualified query
            topic_hint = last_topics[0].rstrip("?. ")
            return f"{question} in context of {topic_hint}"

        return question

    @staticmethod
    def generate_multi_queries(query: str) -> list[str]:
        """Generate paraphrased query variations to maximize recall."""
        variations = [query]
        clean_q = re.sub(r"[?!.,]", "", query).strip()

        # Add targeted keyword and semantic variants
        if any(w in clean_q.lower() for w in ["difference", "compare", "vs", "versus"]):
            subjects = [
                w.strip()
                for w in re.split(
                    r"\b(?:between|and|vs|versus|difference)\b", clean_q, flags=re.IGNORECASE
                )
                if len(w.strip()) > 1
            ]
            if len(subjects) >= 2:
                variations.append(f"{subjects[0]} {subjects[1]}")
                variations.append(f"{subjects[0]} vs {subjects[1]}")
            else:
                variations.append(clean_q.replace("Difference Between", "").strip())
        else:
            variations.append(f"overview {clean_q}")
            variations.append(f"details of {clean_q}")
        return variations[:3]


class RetrievalEngine:
    """Enterprise multi-tenant hybrid retrieval engine."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.rewriter = QueryRewriter()
        self.reranker = CrossEncoderReranker()

    async def dense_search(
        self, query_vec: list[float], org_id: uuid.UUID, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Dense semantic search using pgvector cosine distance, strictly tenant-isolated."""
        vec_str = "[" + ",".join(f"{x:.6f}" for x in query_vec) + "]"
        query = text(
            """
            SELECT CAST(c.id AS text), c.content, c.page_number, CAST(c.document_id AS text),
                   c.section_title, c.element_type, d.filename,
                   1 - (c.embedding <=> CAST(:qvec AS vector)) AS score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.org_id = :org_id
            ORDER BY c.embedding <=> CAST(:qvec AS vector)
            LIMIT :limit;
            """
        )
        try:
            result = await self.db.execute(
                query, {"qvec": vec_str, "org_id": org_id, "limit": limit}
            )
            rows = result.fetchall()
            return [
                {
                    "id": str(r[0]),
                    "content": r[1],
                    "page_number": r[2],
                    "document_id": str(r[3]),
                    "section_title": r[4],
                    "element_type": r[5],
                    "filename": r[6],
                    "score": float(r[7]) if r[7] is not None else 0.0,
                    "search_type": "dense",
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"Dense vector search failed: {e}. Falling back to content search.")
            await self.db.rollback()
            return []

    async def sparse_search(
        self, query_text: str, org_id: uuid.UUID, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Sparse BM25 search using PostgreSQL ts_rank_cd, strictly tenant-isolated."""
        clean_text = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", query_text)
        clean_text = re.sub(r"[^\w\s]", " ", clean_text).strip()
        if not clean_text:
            return []

        # Combined tsvector search across content and section_title using plainto_tsquery
        query = text(
            """
            SELECT CAST(c.id AS text), c.content, c.page_number, CAST(c.document_id AS text),
                   c.section_title, c.element_type, d.filename,
                   ts_rank_cd((to_tsvector('english', COALESCE(c.section_title, '')) || c.content_tsv), plainto_tsquery('english', :q)) AS score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.org_id = :org_id
              AND (to_tsvector('english', COALESCE(c.section_title, '')) || c.content_tsv) @@ plainto_tsquery('english', :q)
            ORDER BY score DESC
            LIMIT :limit;
            """
        )
        try:
            result = await self.db.execute(
                query, {"q": clean_text, "org_id": org_id, "limit": limit}
            )
            rows = result.fetchall()
            if rows:
                return [
                    {
                        "id": str(r[0]),
                        "content": r[1],
                        "page_number": r[2],
                        "document_id": str(r[3]),
                        "section_title": r[4],
                        "element_type": r[5],
                        "filename": r[6],
                        "score": float(r[7]) if r[7] is not None else 0.0,
                        "search_type": "sparse",
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"Full-text search fallback triggered: {e}")
            await self.db.rollback()

        # Fallback ILIKE search on both content and section_title
        words = [
            w
            for w in clean_text.split()
            if len(w) >= 3
            and w.lower() not in {"and", "the", "for", "with", "between", "what", "from"}
        ]
        kw_pattern = f"%{words[0]}%" if words else f"%{clean_text[:50]}%"
        fallback_query = text(
            """
            SELECT CAST(c.id AS text), c.content, c.page_number, CAST(c.document_id AS text),
                   c.section_title, c.element_type, d.filename, 0.5 AS score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.org_id = :org_id
              AND (c.content ILIKE :q_pattern OR c.section_title ILIKE :q_pattern)
            LIMIT :limit;
            """
        )
        try:
            result = await self.db.execute(
                fallback_query,
                {"org_id": org_id, "q_pattern": kw_pattern, "limit": limit},
            )
            rows = result.fetchall()
            return [
                {
                    "id": str(r[0]),
                    "content": r[1],
                    "page_number": r[2],
                    "document_id": str(r[3]),
                    "section_title": r[4],
                    "element_type": r[5],
                    "filename": r[6],
                    "score": float(r[7]),
                    "search_type": "sparse_fallback",
                }
                for r in rows
            ]
        except Exception:
            await self.db.rollback()
            return []

    async def get_chunks_by_ids(
        self, chunk_ids: list[str], org_id: uuid.UUID
    ) -> dict[str, dict[str, Any]]:
        """Fetch chunks by IDs strictly scoped to the tenant organization."""
        if not chunk_ids:
            return {}

        query = text(
            """
            SELECT CAST(c.id AS text), c.content, c.page_number, CAST(c.document_id AS text),
                   c.section_title, c.element_type, d.filename
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE CAST(c.id AS text) = ANY(:chunk_ids)
              AND c.org_id = :org_id;
            """
        )
        try:
            result = await self.db.execute(query, {"chunk_ids": chunk_ids, "org_id": org_id})
            rows = result.fetchall()
            lookup = {}
            for r in rows:
                lookup[str(r[0])] = {
                    "id": str(r[0]),
                    "content": r[1],
                    "page_number": r[2],
                    "document_id": str(r[3]),
                    "section_title": r[4],
                    "element_type": r[5],
                    "filename": r[6],
                }
            return lookup
        except Exception as e:
            logger.warning(f"Fetch chunks by ids failed: {e}")
            await self.db.rollback()
            return {}

    async def retrieve(
        self,
        question: str,
        org_id: uuid.UUID,
        history: list[dict[str, str]] | None = None,
        config: RetrievalConfig | None = None,
    ) -> list[dict[str, Any]]:
        """End-to-end multi-tenant retrieval pipeline executing v1, v2, or v3."""
        cfg = config or RetrievalConfig.from_version(settings.RETRIEVAL_VERSION)
        logger.info(f"Executing retrieval pipeline [{cfg.version}] for org {org_id}")

        # Step 1: Query rewriting
        standalone = (
            self.rewriter.to_standalone(question, history or []) if cfg.rewrite else question
        )

        # Step 2: Multi-query expansion
        queries = [standalone]
        if cfg.multi_query:
            queries = self.rewriter.generate_multi_queries(standalone)

        # Step 3: Embed queries
        query_vectors = [embedding_service.embed_query(q) for q in queries]

        # Step 4: Sequential dense and sparse search to ensure AsyncSession safety
        dense_results = []
        for qvec in query_vectors:
            dense_results.append(await self.dense_search(qvec, org_id, cfg.dense_top_k))

        ranked_lists: list[list[str]] = []
        item_cache: dict[str, dict[str, Any]] = {}

        for res in dense_results:
            id_list = []
            for item in res:
                c_id = item["id"]
                id_list.append(c_id)
                if c_id not in item_cache:
                    item_cache[c_id] = item
            ranked_lists.append(id_list)

        if cfg.hybrid:
            sparse_results = []
            for q in queries:
                sparse_results.append(await self.sparse_search(q, org_id, cfg.sparse_top_k))
            for res in sparse_results:
                id_list = []
                for item in res:
                    c_id = item["id"]
                    id_list.append(c_id)
                    if c_id not in item_cache:
                        item_cache[c_id] = item
                ranked_lists.append(id_list)

        # Step 5: Reciprocal Rank Fusion
        fused_ids = reciprocal_rank_fusion(ranked_lists, top_n=cfg.fusion_top_n)

        # Retrieve full candidate records
        missing_ids = [cid for cid in fused_ids if cid not in item_cache]
        if missing_ids:
            fetched = await self.get_chunks_by_ids(missing_ids, org_id)
            item_cache.update(fetched)

        candidates = [item_cache[cid] for cid in fused_ids if cid in item_cache]

        # Step 6: Cross-Encoder Re-ranking
        if cfg.rerank and len(candidates) > 1:
            candidates = self.reranker.rank(standalone, candidates, top_k=cfg.final_k)
        else:
            candidates = candidates[: cfg.final_k]

        return candidates
