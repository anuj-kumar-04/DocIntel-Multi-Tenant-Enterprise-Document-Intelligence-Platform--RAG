import re
import uuid
from typing import Any

from app.config import settings
from app.core.logging import logger
from app.services.embeddings import embedding_service
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")

# Stopwords stripped before keyword/BM25 matching so natural questions don't fail on filler words
_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "all",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "based",
        "be",
        "been",
        "being",
        "between",
        "by",
        "can",
        "check",
        "complete",
        "could",
        "details",
        "did",
        "do",
        "document",
        "documents",
        "does",
        "during",
        "explain",
        "file",
        "for",
        "from",
        "get",
        "give",
        "got",
        "had",
        "has",
        "have",
        "he",
        "her",
        "here",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "me",
        "might",
        "must",
        "my",
        "of",
        "on",
        "only",
        "or",
        "other",
        "our",
        "out",
        "over",
        "overview",
        "pdf",
        "please",
        "shall",
        "she",
        "should",
        "show",
        "tell",
        "that",
        "the",
        "their",
        "them",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "under",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

_SCOPED_FULL_DOC_MAX_CHUNKS = 30
_SCOPED_FULL_DOC_MAX_TOKENS = 12000


def _clean_str(value: str | None) -> str:
    return _INVISIBLE_RE.sub("", value or "").strip()


def _extract_keywords(query_text: str) -> list[str]:
    """Extract normalized alphanumeric search terms excluding filler/question words."""
    clean = _clean_str(query_text).lower()
    raw_words = re.findall(r"[a-z0-9]+", clean)
    keywords = [w for w in raw_words if len(w) >= 2 and w not in _STOPWORDS]
    # Preserve insertion order while deduplicating
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    if not unique:
        return [w for w in raw_words if len(w) >= 2][:4]
    return unique


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
            if settings.ENVIRONMENT == "test":
                self._initialized = True
                return None
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
                    sec = _clean_str(c.get("section_title"))
                    content = _clean_str(c.get("content"))
                    doc_text = f"{sec}\n{content}" if sec else content
                    pairs.append([query, doc_text])
                scores = model.predict(pairs)
                for c, s in zip(candidates, scores, strict=False):
                    c["rerank_score"] = float(s)
                return sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)[:top_k]
            except Exception as e:
                logger.warning(f"Cross-encoder scoring error: {e}")

        # Fallback lexical and prefix-stem scoring excluding stopwords
        q_keywords = _extract_keywords(query)
        q_tokens = q_keywords or re.findall(r"[a-z0-9]+", _clean_str(query).lower())

        for c in candidates:
            raw_text = f"{c.get('content', '')} {c.get('section_title') or ''}"
            clean_text = _clean_str(raw_text).lower()
            doc_words = set(re.findall(r"[a-z0-9]+", clean_text))

            overlap = 0.0
            for kw in q_tokens:
                if kw in doc_words or kw in clean_text:
                    overlap += 1.0
                elif len(kw) >= 4 and kw[:4] in clean_text:
                    # Partial inflection stem credit (e.g. "opened" matching "unopened")
                    overlap += 0.6

            density = overlap / (len(q_tokens) + 1e-5)
            type_boost = (
                1.15 if c.get("element_type") == "table" or "|" in c.get("content", "") else 1.0
            )
            sec_lower = _clean_str(c.get("section_title")).lower()
            title_boost = 1.2 if sec_lower and any(w in sec_lower for w in q_tokens) else 1.0
            c["rerank_score"] = density * type_boost * title_boost

        return sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)[:top_k]


class QueryRewriter:
    """Conversational standalone query reformer and multi-query generator."""

    @staticmethod
    def to_standalone(question: str, history: list[dict[str, str]]) -> str:
        """Resolve pronouns and coreferences into a self-contained query."""
        if not history:
            return question

        last_topics = []
        for msg in reversed(history[-4:]):
            if msg.get("role") == "user":
                last_topics.append(msg.get("content", ""))

        if not last_topics:
            return question

        q_lower = question.lower()
        pronouns = ["it", "its", "they", "their", "this", "that", "these", "those", "he", "she"]
        if any(re.search(rf"\b{p}\b", q_lower) for p in pronouns):
            topic_hint = last_topics[0].rstrip("?. ")
            return f"{question} in context of {topic_hint}"

        return question

    @staticmethod
    def generate_multi_queries(query: str) -> list[str]:
        """Generate focused query variations without polluting keywords with generic filler terms."""
        variations = [query]
        clean_q = re.sub(r"[?!.,]", "", query).strip()
        keywords = _extract_keywords(clean_q)

        if any(w in clean_q.lower() for w in ["difference", "compare", "vs", "versus"]):
            subjects = [
                w.strip()
                for w in re.split(
                    r"\b(?:between|and|vs|versus|difference|differences)\b",
                    clean_q,
                    flags=re.IGNORECASE,
                )
                if len(w.strip()) > 1
            ]
            if len(subjects) >= 2:
                variations.append(f"{subjects[0]} {subjects[1]}")
                variations.append(f"{subjects[0]} vs {subjects[1]}")
            elif keywords:
                variations.append(" ".join(keywords))
        else:
            if keywords:
                variations.append(" ".join(keywords))
                if len(keywords) >= 2:
                    variations.append(f"{keywords[0]} {keywords[-1]}")
            elif clean_q and clean_q != query:
                variations.append(clean_q)

        # Deduplicate preserving order while guaranteeing >= 2 entries when keywords differ
        deduped: list[str] = []
        for v in variations:
            if v and v not in deduped:
                deduped.append(v)
        if len(deduped) == 1:
            deduped.append(clean_q or query)
        return deduped[:3]


class RetrievalEngine:
    """Enterprise multi-tenant hybrid retrieval engine with optional strict PDF scoping."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.rewriter = QueryRewriter()
        self.reranker = CrossEncoderReranker()

    @staticmethod
    def _build_doc_filter(document_ids: list[uuid.UUID] | None) -> tuple[str, dict[str, Any]]:
        if not document_ids:
            return "", {}
        return " AND CAST(c.document_id AS text) = ANY(:doc_ids)", {
            "doc_ids": [str(d) for d in document_ids]
        }

    @staticmethod
    def _row_to_chunk_dict(row: Any, search_type: str | None = None) -> dict[str, Any]:
        item: dict[str, Any] = {
            "id": str(row[0]),
            "content": row[1],
            "page_number": row[2],
            "document_id": str(row[3]),
            "section_title": row[4],
            "element_type": row[5],
            "filename": row[6],
        }
        if len(row) > 7 and row[7] is not None:
            item["score"] = float(row[7])
        if search_type:
            item["search_type"] = search_type
        return item

    async def dense_search(
        self,
        query_vec: list[float],
        org_id: uuid.UUID,
        limit: int = 20,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[dict[str, Any]]:
        """Dense semantic search using pgvector cosine distance, strictly tenant/doc-isolated."""
        vec_str = "[" + ",".join(f"{x:.6f}" for x in query_vec) + "]"
        doc_clause, doc_params = self._build_doc_filter(document_ids)
        query = text(
            f"""
            SELECT CAST(c.id AS text), c.content, c.page_number, CAST(c.document_id AS text),
                   c.section_title, c.element_type, d.filename,
                   1 - (c.embedding <=> CAST(:qvec AS vector)) AS score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.org_id = :org_id {doc_clause}
            ORDER BY c.embedding <=> CAST(:qvec AS vector)
            LIMIT :limit;
            """
        )
        try:
            params = {"qvec": vec_str, "org_id": org_id, "limit": limit, **doc_params}
            result = await self.db.execute(query, params)
            return [self._row_to_chunk_dict(r, "dense") for r in result.fetchall()]
        except Exception as e:
            logger.warning(f"Dense vector search failed: {e}. Falling back to content search.")
            await self.db.rollback()
            return []

    async def sparse_search(
        self,
        query_text: str,
        org_id: uuid.UUID,
        limit: int = 20,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[dict[str, Any]]:
        """Sparse BM25 search using Postgres FTS (AND + OR keywords) strictly scoped to tenant/docs."""
        keywords = _extract_keywords(query_text)
        if not keywords:
            return []

        doc_clause, doc_params = self._build_doc_filter(document_ids)
        kw_phrase = " ".join(keywords)
        safe_ts_terms = [re.sub(r"[^a-z0-9]", "", kw) for kw in keywords[:10]]
        safe_ts_terms = [t for t in safe_ts_terms if t]
        or_tsquery = " | ".join(f"{t}:*" if len(t) >= 4 else t for t in safe_ts_terms)

        # Stage 1: Exact-all-keywords AND match boosted cleanly, unioned with OR keyword rank
        # so multi-clause questions still retrieve partial keyword matches from the right PDF.
        if or_tsquery:
            fts_query = text(
                f"""
                WITH fts_hits AS (
                    SELECT CAST(c.id AS text) AS id, c.content, c.page_number,
                           CAST(c.document_id AS text) AS document_id,
                           c.section_title, c.element_type, d.filename,
                           (
                               CASE
                                   WHEN (to_tsvector('english', COALESCE(c.section_title, '')) || c.content_tsv) @@ plainto_tsquery('english', :q_and)
                                   THEN 2.0 + ts_rank_cd((to_tsvector('english', COALESCE(c.section_title, '')) || c.content_tsv), plainto_tsquery('english', :q_and))
                                   ELSE ts_rank_cd((to_tsvector('english', COALESCE(c.section_title, '')) || c.content_tsv), to_tsquery('english', :q_or))
                               END
                           ) AS score
                    FROM chunks c
                    JOIN documents d ON c.document_id = d.id
                    WHERE c.org_id = :org_id {doc_clause}
                      AND (to_tsvector('english', COALESCE(c.section_title, '')) || c.content_tsv) @@ to_tsquery('english', :q_or)
                )
                SELECT * FROM fts_hits
                ORDER BY score DESC
                LIMIT :limit;
                """
            )
            try:
                params = {
                    "q_and": kw_phrase,
                    "q_or": or_tsquery,
                    "org_id": org_id,
                    "limit": limit,
                    **doc_params,
                }
                result = await self.db.execute(fts_query, params)
                rows = result.fetchall()
                if rows:
                    return [self._row_to_chunk_dict(r, "sparse") for r in rows]
            except Exception as e:
                logger.warning(f"Full-text search fallback triggered: {e}")
                await self.db.rollback()

        # Stage 2: Multi-keyword ILIKE scoring fallback (scores across ALL meaningful keywords)
        top_kws = keywords[:6]
        score_parts = []
        where_parts = []
        ilike_params: dict[str, Any] = {"org_id": org_id, "limit": limit, **doc_params}
        for idx, kw in enumerate(top_kws):
            pname = f"kw_{idx}"
            ilike_params[pname] = f"%{kw}%"
            cond = f"(c.content ILIKE :{pname} OR COALESCE(c.section_title, '') ILIKE :{pname})"
            score_parts.append(f"(CASE WHEN {cond} THEN 1 ELSE 0 END)")
            where_parts.append(cond)

        fallback_query = text(
            f"""
            SELECT CAST(c.id AS text), c.content, c.page_number, CAST(c.document_id AS text),
                   c.section_title, c.element_type, d.filename,
                   CAST(({" + ".join(score_parts)}) AS float) AS score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.org_id = :org_id {doc_clause}
              AND ({" OR ".join(where_parts)})
            ORDER BY score DESC
            LIMIT :limit;
            """
        )
        try:
            result = await self.db.execute(fallback_query, ilike_params)
            return [self._row_to_chunk_dict(r, "sparse_fallback") for r in result.fetchall()]
        except Exception:
            await self.db.rollback()
            return []

    async def get_chunks_by_ids(
        self,
        chunk_ids: list[str],
        org_id: uuid.UUID,
        document_ids: list[uuid.UUID] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Fetch chunks by IDs strictly scoped to the tenant organization and optional documents."""
        if not chunk_ids:
            return {}

        doc_clause, doc_params = self._build_doc_filter(document_ids)
        query = text(
            f"""
            SELECT CAST(c.id AS text), c.content, c.page_number, CAST(c.document_id AS text),
                   c.section_title, c.element_type, d.filename
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE CAST(c.id AS text) = ANY(:chunk_ids)
              AND c.org_id = :org_id {doc_clause};
            """
        )
        try:
            params = {"chunk_ids": chunk_ids, "org_id": org_id, **doc_params}
            result = await self.db.execute(query, params)
            lookup = {}
            for r in result.fetchall():
                lookup[str(r[0])] = self._row_to_chunk_dict(r)
            return lookup
        except Exception as e:
            logger.warning(f"Fetch chunks by ids failed: {e}")
            await self.db.rollback()
            return {}

    async def _fetch_scoped_document_chunks(
        self,
        org_id: uuid.UUID,
        document_ids: list[uuid.UUID],
    ) -> list[dict[str, Any]]:
        """Fetch all ordered chunks for explicitly scoped documents."""
        doc_clause, doc_params = self._build_doc_filter(document_ids)
        query = text(
            f"""
            SELECT CAST(c.id AS text), c.content, c.page_number, CAST(c.document_id AS text),
                   c.section_title, c.element_type, d.filename,
                   c.chunk_index, c.token_count
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.org_id = :org_id {doc_clause}
            ORDER BY d.filename ASC, c.page_number ASC, c.chunk_index ASC;
            """
        )
        try:
            result = await self.db.execute(query, {"org_id": org_id, **doc_params})
            chunks = []
            for r in result.fetchall():
                chunks.append(
                    {
                        "id": str(r[0]),
                        "content": r[1],
                        "page_number": r[2],
                        "document_id": str(r[3]),
                        "section_title": r[4],
                        "element_type": r[5],
                        "filename": r[6],
                        "chunk_index": int(r[7] or 0),
                        "token_count": int(r[8] or 0),
                        "score": 1.0,
                        "search_type": "complete_document",
                    }
                )
            return chunks
        except Exception as e:
            logger.warning(f"Scoped full-document fetch failed: {e}")
            await self.db.rollback()
            return []

    @staticmethod
    def _expand_scoped_neighbors(
        selected: list[dict[str, Any]],
        all_ordered: list[dict[str, Any]],
        max_tokens: int = _SCOPED_FULL_DOC_MAX_TOKENS,
    ) -> list[dict[str, Any]]:
        """Include immediate sibling chunks around top hits within the token budget."""
        selected_keys = {(c["document_id"], c.get("chunk_index", 0)) for c in selected}
        expanded_keys = set(selected_keys)
        for doc_id, idx in selected_keys:
            expanded_keys.add((doc_id, idx - 1))
            expanded_keys.add((doc_id, idx + 1))

        kept: list[dict[str, Any]] = []
        running_tokens = 0
        for chunk in all_ordered:
            key = (chunk["document_id"], chunk.get("chunk_index", 0))
            if key in expanded_keys:
                toks = int(chunk.get("token_count") or max(1, len(chunk["content"].split())))
                if kept and running_tokens + toks > max_tokens:
                    break
                kept.append(chunk)
                running_tokens += toks
        return kept

    async def retrieve(
        self,
        question: str,
        org_id: uuid.UUID,
        history: list[dict[str, str]] | None = None,
        config: RetrievalConfig | None = None,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[dict[str, Any]]:
        """End-to-end multi-tenant retrieval pipeline with optional complete-PDF scoping."""
        cfg = config or RetrievalConfig.from_version(settings.RETRIEVAL_VERSION)
        logger.info(
            f"Executing retrieval pipeline [{cfg.version}] for org {org_id} "
            f"(scoped_docs={len(document_ids) if document_ids else 'all'})"
        )

        # Complete-policy mode: when pinned to specific PDF(s), never cross-contaminate other PDFs.
        # If the scoped PDF(s) fit cleanly within the token budget, read the entire PDF(s) in order.
        ordered_scoped: list[dict[str, Any]] | None = None
        if document_ids:
            ordered_scoped = await self._fetch_scoped_document_chunks(org_id, document_ids)
            if not ordered_scoped:
                return []
            total_tokens = sum(int(c.get("token_count") or 0) for c in ordered_scoped)
            if (
                len(ordered_scoped) <= _SCOPED_FULL_DOC_MAX_CHUNKS
                and total_tokens <= _SCOPED_FULL_DOC_MAX_TOKENS
            ):
                logger.info(
                    f"Complete-document context active ({len(ordered_scoped)} chunks, {total_tokens} tokens)"
                )
                return ordered_scoped

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

        # Step 4: Sequential dense and sparse search strictly scoped to org + optional document_ids
        search_dense_k = max(cfg.dense_top_k, 25) if document_ids else cfg.dense_top_k
        search_sparse_k = max(cfg.sparse_top_k, 25) if document_ids else cfg.sparse_top_k

        dense_results = []
        for qvec in query_vectors:
            dense_results.append(
                await self.dense_search(qvec, org_id, search_dense_k, document_ids=document_ids)
            )

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
                sparse_results.append(
                    await self.sparse_search(q, org_id, search_sparse_k, document_ids=document_ids)
                )
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
            fetched = await self.get_chunks_by_ids(missing_ids, org_id, document_ids=document_ids)
            item_cache.update(fetched)

        candidates = [item_cache[cid] for cid in fused_ids if cid in item_cache]

        target_k = max(cfg.final_k, 12) if document_ids else cfg.final_k

        # Step 6: Cross-Encoder Re-ranking
        if cfg.rerank and len(candidates) > 1:
            candidates = self.reranker.rank(standalone, candidates, top_k=target_k)
        else:
            candidates = candidates[:target_k]

        # Step 7: For large scoped PDFs, include neighboring chunks so policy sub-clauses stay intact
        if document_ids and ordered_scoped:
            if not candidates:
                return ordered_scoped[:12]
            ordered_by_id = {c["id"]: c for c in ordered_scoped}
            enriched = [ordered_by_id.get(c["id"], c) for c in candidates]
            return self._expand_scoped_neighbors(enriched, ordered_scoped)

        return candidates
