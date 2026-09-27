# DocIntel — Platform Explained

Welcome to **DocIntel**, an enterprise-grade, multi-tenant document intelligence platform designed to ingest complex organizational documents (PDFs, Word documents, Excel spreadsheets), index them using layout-aware chunking and hybrid retrieval, and answer natural-language questions with verified, page-level inline citations.

---

## 1. What the Project Does

In modern enterprises, critical knowledge is siloed across thousands of annual reports, security policies, supplier contracts, and financial spreadsheets. Naive search tools fail because:
1. They cannot search tables accurately.
2. They hallucinate facts and invent answers.
3. They leak confidential data across organizational boundaries.
4. They provide answers without proof, forcing human analysts to re-read the entire document.

**DocIntel solves this end-to-end**:
- **Multi-Tenancy**: Organization A can never search, see, or cite documents belonging to Organization B. Tenant isolation is enforced in SQL queries (`WHERE org_id = :org_id`), not in application code.
- **Asynchronous Ingestion**: Heavy document parsing and embedding are handled by background Celery worker processes with retry policies, keeping web requests fast and non-blocking.
- **Section-Aware Hybrid Retrieval (Dense + Sparse BM25)**: Combines semantic vector similarity (pgvector) with full-text search over concatenated `(to_tsvector(section_title) || content_tsv)`. This ensures standalone tables and lists separated from their parent headings across page boundaries are still retrieved with high precision.
- **Invisible PDF Unicode Sanitization**: Automatically cleans directional formatting artifacts (`\u202d` LTR override, `\u202c` POP, zero-width spaces) common in Google Docs and Word PDF exports that disrupt tokenizers and text matchers.
- **Cross-Encoder Re-ranking**: Evaluates joint query-document interactions (including section titles) to ensure that the top candidates are genuinely relevant.
- **Strict Grounded Citations**: Answers must cite their source using bracketed numbers `[1]`, `[2]`. Any hallucinated citations are automatically stripped, and clicking a citation badge opens the exact source excerpt, section name, and page number.
- **Cost & Quota Governance**: Enforces monthly token budgets per tenant, caches frequent questions with a sub-millisecond Redis semantic vector cache, and routes LLM requests across Groq, Gemini, OpenAI, and a local grounded engine with automatic fallback.

---

## 2. How the Pieces Connect

```
1. Upload Document ──▶ S3 / MinIO ──▶ Celery Task ──▶ PyMuPDF / Extraction ──▶ Unicode Clean & Chunking ──▶ Embeddings ──▶ pgvector Chunks
                                                                                                                              │
2. User Question ──▶ Semantic Cache (Redis) ──Hit──▶ Return Cached Answer + Citations                                        │
                           │ Miss                                                                                             │
                           ▼                                                                                                  │
                   Query Rewriter (Standalone + Multi-Query Paraphraser)                                                      │
                           │                                                                                                  │
                           ▼                                                                                                  │
                   Parallel Search: Dense (pgvector HNSW) + Sparse (BM25 on Title + Content) ◀────────────────────────────────┘
                           │
                           ▼
                   Reciprocal Rank Fusion (RRF) ──▶ Top 30 Candidates
                           │
                           ▼
                   Cross-Encoder Re-ranker (Scoring Title + Content) ──▶ Top 6 Grounding Chunks
                           │
                           ▼
                   Section-Aware Context Builder (Injects Page, Filename & Section Metadata)
                           │
                           ▼
                   Multi-Model Router Cascade (Groq Qwen/Llama ➡️ Gemini Flash ➡️ OpenAI ➡️ Local Engine)
                           │
                           ▼
                   Citation Post-Check (Validate [n], purge hallucinated indices)
                           │
                           ▼
                   SSE Streaming Response (Token-by-token + verified citation cards)
```

---

## 3. How to Run & Verify the Platform

### Running with Docker Compose (Recommended)
```bash
# 1. Initialize environment
cp .env.example .env

# 2. Start all services
docker compose up -d

# 3. Apply database migrations
docker compose exec api alembic upgrade head

# 4. Seed realistic demo data
docker compose exec api python app/scripts/seed.py
```

### Running Locally with Python
```bash
# 1. Install dependencies
cd backend
python -m pip install -r requirements.txt

# 2. Seed database
python app/scripts/seed.py

# 3. Start API server
uvicorn app.main:app --port 8000 --reload
```

Then visit:
- **Executive Standalone Dashboard**: [http://localhost:8000/app/index.html](http://localhost:8000/app/index.html)
- **API Swagger Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Metrics**: [http://localhost:8000/metrics](http://localhost:8000/metrics)

---

## 4. Glossary of Key Technical Terms

| Term | Meaning & Purpose in DocIntel |
|---|---|
| **Multi-Tenancy** | An architecture where multiple organizations share the same infrastructure and database while guaranteeing strict data isolation so no tenant can ever view another tenant's data. |
| **Denormalized Tenant Key** | Storing `org_id` directly on the `chunks` table so vector similarity searches can filter by tenant inside the relational query (`WHERE org_id = :org_id`) without an expensive table JOIN. |
| **pgvector** | An open-source PostgreSQL extension that stores vector embeddings as native columns and enables approximate nearest neighbor (ANN) searches using HNSW or IVFFlat indexes. |
| **HNSW (Hierarchical Navigable Small World)** | A graph-based multi-layer indexing algorithm for vectors providing logarithmic search time $O(\log N)$ with high recall. |
| **Sparse Retrieval (BM25)** | A term-frequency/inverse-document-frequency probabilistic search algorithm. In DocIntel, implemented via PostgreSQL `tsvector` and `ts_rank_cd` to match exact keywords and numbers. |
| **Dense Retrieval** | Semantic search using bi-encoder transformer embeddings where similarity is measured by cosine distance between vector coordinates. |
| **Reciprocal Rank Fusion (RRF)** | An algorithmic method for combining multiple ranked lists by summing the reciprocal of each item's rank ($1 / (k + \text{rank})$). Overcomes incomparable score scales between dense cosine and BM25 scores. |
| **Cross-Encoder Re-ranker** | A neural model that jointly computes cross-attention over the query and document chunk simultaneously, achieving significantly higher precision than bi-encoders at the cost of higher compute per candidate. |
| **Semantic Cache** | A caching mechanism in Redis that embeds incoming questions and returns pre-computed answers if the cosine similarity against a previously asked question exceeds $0.97$. |
| **Server-Sent Events (SSE)** | A lightweight HTTP standard where a server pushes real-time text updates (tokens, citations, completion events) over a single persistent connection without the bidirectional overhead of WebSockets. |
| **Section-Aware Retrieval** | Full-text and vector querying that concatenates section titles with content bodies `(to_tsvector(section_title) || content_tsv)`. This guarantees that isolated tables or lists whose headings reside on previous pages are never lost during retrieval. |
| **Bidirectional Unicode Sanitization** | Removing invisible formatting markers (`\u202d`, `\u202c`, zero-width spaces, BOM) injected by word processors and PDF printers that corrupt lexical search and tokenization. |
| **Citation Verification Engine** | A deterministic post-processor that scans LLM answers for bracketed citations `[n]`, cross-references them against the retrieved source map, strips hallucinated citation numbers, and pairs valid citations with page and section metadata. |
| **LiteLLM** | A unified proxy and router library that standardizes calls to OpenAI, Groq, Anthropic, and Gemini, providing automatic fallback routing and token cost tracking. |
| **RAGAS** | Retrieval Augmented Generation Assessment, an industry evaluation framework measuring Faithfulness, Answer Relevancy, Context Precision, and Context Recall against ground-truth benchmarks. |
