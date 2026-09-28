# DocIntel — Platform Explained

Welcome to **DocIntel**, an enterprise-grade, multi-tenant document intelligence platform designed to ingest complex organizational documents (PDFs, Word documents, Excel spreadsheets), index them using layout-aware chunking and hybrid retrieval, and answer natural-language questions with verified, page-level inline citations.

---

## 1. What the Project Does & Core Problem Statement

In modern enterprises, critical knowledge is siloed across thousands of annual reports, security policies, supplier contracts, and financial spreadsheets. Naive search tools and basic RAG implementations fail in production because:
1. **They cannot search tables accurately**: Page splits and un-parsed Markdown grids destroy table coherence.
2. **They hallucinate facts**: Models invent facts, extrapolate percentages, and cite non-existent sources.
3. **They leak confidential data**: Without kernel-level database isolation, tenant documents can bleed across queries.
4. **They lack verifiable proof**: Users are given raw text answers without exact source page citations, forcing manual verification.
5. **They suffer from brittle infrastructure**: Single-model rate limits cause outages, and duplicate uploads waste costly embedding computations.

**DocIntel solves these challenges end-to-end**:
- **Zero-Leak Multi-Tenancy**: Organization A can never search, see, or cite documents belonging to Organization B. Tenant isolation is enforced in SQL queries (`WHERE org_id = :org_id`), not in application code.
- **Asynchronous Ingestion**: Heavy document parsing and embedding are handled by background Celery worker processes with retry policies, keeping web requests fast and non-blocking.
- **Section-Aware Hybrid Retrieval (Dense + Sparse BM25)**: Combines semantic vector similarity (`pgvector`) with full-text search over concatenated `(to_tsvector(section_title) || content_tsv)`. This ensures standalone tables and lists separated from their parent headings across page boundaries are still retrieved with high precision.
- **Invisible PDF Unicode Sanitization**: Automatically cleans directional formatting artifacts (`\u202d` LTR override, `\u202c` POP, zero-width spaces) common in Google Docs and Word PDF exports that disrupt tokenizers and text matchers.
- **Cross-Encoder Re-ranking**: Evaluates joint query-document interactions (including section titles) to ensure that the top candidates are genuinely relevant.
- **Strict Grounded Citations**: Answers must cite their source using bracketed numbers `[1]`, `[2]`. Any hallucinated citations are automatically stripped, and clicking a citation badge opens the exact source excerpt, section name, and page number.
- **Cost & Quota Governance**: Enforces monthly token budgets per tenant, caches frequent questions with a sub-millisecond Redis semantic vector cache, and routes LLM requests across Groq, Gemini, OpenAI, and a local grounded engine with automatic fallback.
- **Automated CI/CD Quality Gates**: 24/24 passing pytest integration tests, 100% clean Ruff linting & import sorting, and an automated RAGAS faithfulness regression gate ($\ge 0.85$).

---

## 2. Annotated Project Directory Structure

```
├── .github/
│   └── workflows/
│       └── ci.yml               # Automated GitHub Actions CI/CD Pipeline
│                                # Runs: Ruff linter & format, Pytest suite (24 tests),
│                                # Docker builds, and RAGAS retrieval regression gate.
├── backend/
│   ├── alembic/                 # Database migrations (PostgreSQL + pgvector schema)
│   │   ├── versions/            # Versioned migration revision scripts
│   │   └── env.py               # Alembic asynchronous runtime environment
│   ├── app/
│   │   ├── api/v1/              # FastAPI REST API Controllers (v1)
│   │   │   ├── admin.py         # Tenant metrics, usage events, and token quota admin
│   │   │   ├── auth.py          # JWT authentication, login, register, and /me endpoint
│   │   │   ├── chat.py          # SSE token streaming & conversational RAG endpoint
│   │   │   ├── documents.py     # Document upload, idempotency check & status endpoints
│   │   │   ├── health.py        # Kubernetes liveness & readiness health checks
│   │   │   └── router.py        # API v1 router registry
│   │   ├── core/                # Core system infrastructure
│   │   │   ├── errors.py        # Standardized HTTP and domain exceptions
│   │   │   ├── logging.py       # Structured JSON logging with correlation IDs
│   │   │   ├── rate_limit.py    # IP/User-based rate limiting via SlowAPI
│   │   │   ├── security.py      # BCrypt password hashing & JWT encoding/decoding
│   │   │   └── tracing.py       # Langfuse distributed tracing instrumentation
│   │   ├── models/              # SQLAlchemy 2.0 Async Database Models
│   │   │   ├── base.py          # Declarative Base metadata
│   │   │   ├── chat.py          # ChatSession and ChatMessage entities
│   │   │   ├── chunk.py         # Document Chunk with pgvector Vector(384) & tsvector
│   │   │   ├── document.py      # Document entity, processing status & SHA-256 hash
│   │   │   ├── org.py           # Organization entity with monthly token budgets
│   │   │   ├── usage.py         # UsageEvent log for cost and token tracking
│   │   │   └── user.py          # User accounts and RBAC roles (Owner, Admin, Member)
│   │   ├── schemas/             # Pydantic v2 validation models & DTOs
│   │   │   ├── admin.py         # Admin management request/response schemas
│   │   │   ├── auth.py          # Login, Register, and Token schemas
│   │   │   ├── chat.py          # Chat message inputs, citations & streaming schemas
│   │   │   └── document.py      # Document upload, status & list schemas
│   │   ├── scripts/             # Operational Scripts
│   │   │   ├── reindex_embeddings.py # Backfill & vector migration utility
│   │   │   └── seed.py          # Seeds sample organizations, users, and documents
│   │   ├── services/            # Core Business & Algorithmic Services
│   │   │   ├── auth_service.py  # User authentication & permission checking
│   │   │   ├── budget.py        # Monthly quota governance & atomic token tracking
│   │   │   ├── cache.py         # Redis semantic vector cache (>0.97 similarity)
│   │   │   ├── chunking.py      # LayoutChunker (section-aware, table preservation)
│   │   │   ├── embeddings.py    # LiteLLM/sentence-transformer embedding generator
│   │   │   ├── generation.py    # LLM cascade router & citation verification engine
│   │   │   ├── parsing.py       # PyMuPDF / docx / openpyxl layout parser + unicode sanitizer
│   │   │   ├── retrieval.py     # Hybrid search (pgvector + BM25 + RRF + Cross-Encoder)
│   │   │   └── storage.py       # Resilient S3/SeaweedFS/MinIO storage with local fallback
│   │   ├── static/              # Embedded Executive Browser Interface
│   │   │   └── index.html       # Single-page executive dashboard with streaming & citations
│   │   ├── workers/             # Asynchronous Celery Workers
│   │   │   ├── celery_app.py    # Celery configuration with Redis broker
│   │   │   └── tasks.py         # Background document processing and vector ingestion
│   │   ├── config.py            # Application settings from environment variables
│   │   ├── deps.py              # FastAPI dependency injection (AsyncSession, User, DB)
│   │   └── main.py              # FastAPI application factory, CORS, Prometheus metrics
│   ├── tests/                   # Automated Pytest Suite (24 tests, 100% passing)
│   │   ├── conftest.py          # Async PostgreSQL test engine, client & tenant fixtures
│   │   ├── test_auth.py         # User registration, login, and RBAC permissions
│   │   ├── test_chat.py         # Conversational endpoints, streaming & quota limits
│   │   ├── test_citations.py    # Inline citation extraction and hallucination purging
│   │   ├── test_ingestion.py    # Document upload, idempotency, chunking & layout tests
│   │   ├── test_retrieval.py    # Hybrid search, BM25, RRF fusion & semantic cache
│   │   └── test_tenant_isolation.py # Cryptographic zero-leak cross-tenant query tests
│   ├── Dockerfile               # Production multi-stage backend Docker container
│   ├── pyproject.toml           # Tooling configuration (Ruff, Mypy, Pytest)
│   └── requirements.txt         # Pinned backend dependencies
├── frontend/                    # Next.js 15 Enterprise Web Application
│   ├── app/                     # App router pages, layouts & providers
│   ├── components/              # UI components (ChatDrawer, FileUploader, CitationCard)
│   ├── lib/                     # API client, SSE stream parsers & auth utilities
│   ├── public/                  # Static assets & brand icons
│   ├── Dockerfile               # Node.js 20 production container
│   ├── package.json             # Frontend dependencies (React 19, Tailwind, shadcn)
│   └── tailwind.config.js       # Styling theme configuration
├── eval/                        # RAGAS Golden Evaluation Suite
│   ├── golden_set.jsonl         # 50 hand-crafted enterprise questions with ground truth
│   └── run_eval.py              # Benchmark execution harness & CI quality regression gate
├── infra/                       # Infrastructure & Observability
│   ├── grafana/                 # Dashboards for token latency, queries & cache hit rate
│   ├── nginx/                   # Nginx reverse proxy configuration & gzip compression
│   └── prometheus/              # Metrics collection rules for FastAPI & Celery
├── ARCHITECTURE.md              # Architectural Decision Records (ADRs) & Interview Guide
├── EVALUATION.md                # In-depth RAGAS benchmark methodology & metric definitions
├── PROJECT_EXPLAINED.md         # Comprehensive end-to-end platform explanation & guide
├── docker-compose.yml           # Complete 7-container local orchestration stack
├── docker-compose.prod.yml      # Hardened production Docker Compose deployment
└── Makefile                     # Developer productivity shortcuts (test, lint, run, seed)
```

---

## 3. End-to-End Execution Lifecycles

### Pipeline 1: Document Ingestion Lifecycle
```
1. Client POST /api/v1/documents (file, JWT)
   │
   ├─► Check MIME type and file size (< 50MB)
   ├─► Calculate SHA-256 hash
   ├─► Check existing documents in same tenant org (status != FAILED) -> Idempotency return
   │
2. Upload to Storage (S3 / SeaweedFS / MinIO)
   │   └─► If remote S3 unavailable: automatically writes to local resilient storage
   │
3. Create Document DB record (status=QUEUED) & Enqueue Celery Task
   │
4. Celery Worker (tasks.process_document)
   │   ├─► Download raw bytes from storage
   │   ├─► DocumentParser: PyMuPDF for PDF, python-docx for DOCX, openpyxl for XLSX
   │   ├─► UnicodeSanitizer: Strip invisible \u202d, \u202c, and zero-width spaces
   │   ├─► LayoutChunker: Section-aware chunking preserving Markdown tables whole
   │   ├─► EmbeddingService: Generate 384-dimensional vector embeddings in batches
   │   ├─► Upsert Chunks into PostgreSQL pgvector with org_id and tsvector
   │   └─► Update Document DB record (status=READY, chunk_count, page_count)
```

### Pipeline 2: Hybrid Retrieval & Re-ranking Lifecycle
```
1. Client POST /api/v1/chat (query, session_id, JWT)
   │
2. Check Redis Semantic Cache
   │   ├─► Embed incoming query
   │   ├─► Cosine similarity comparison against cached queries for this tenant
   │   └─► If similarity >= 0.97: Return cached tokens + verified citations immediately (<15ms)
   │
3. Query Rewriter (QueryRewriter)
   │   ├─► Reformulates conversational follow-ups into standalone search queries
   │   └─► Generates multi-query paraphrases for high recall
   │
4. Parallel Execution: Dense + Sparse Search
   │   ├─► Dense Vector Search (pgvector):
   │   │     SELECT c.*, 1 - (c.embedding <=> :qvec) AS score FROM chunks c
   │   │     WHERE c.org_id = :org_id ORDER BY c.embedding <=> :qvec LIMIT 20
   │   │
   │   └─► Sparse Keyword Search (PostgreSQL BM25 tsvector):
   │         SELECT c.*, ts_rank_cd(to_tsvector('english', c.section_title) || c.content_tsv, ...)
   │         WHERE c.org_id = :org_id AND ... LIMIT 20
   │
5. Reciprocal Rank Fusion (RRF)
   │   └─► RRF Score = 1 / (60 + DenseRank) + 1 / (60 + SparseRank)
   │   └─► Merge into Top 30 candidate pool
   │
6. Cross-Encoder Re-ranker (CrossEncoderReranker)
   │   └─► Joint cross-attention scoring: [Query, Section Title + Content]
   │   └─► Select Top 6 highest scoring chunks for grounding
```

### Pipeline 3: Generation & Citation Verification Lifecycle
```
1. Build Grounded Context Prompt
   │   └─► Format each chunk with clear headers:
   │         [CHUNK 1] (File: q4_report.pdf, Section: Revenue, Page: 4)
   │         ...content...
   │
2. Multi-Model Router Cascade (LiteLLM)
   │   ├─► Primary: Groq (Qwen 2.5 32B / Llama 3.3 70B) -> Ultra-low latency streaming
   │   ├─► Failover 1: Google Gemini Flash
   │   ├─► Failover 2: OpenAI GPT-4o-mini
   │   └─► Fallback 3: Local Smart Grounded Extractor (Zero-cloud-dependency guarantee)
   │
3. Citation Verification Engine (verify_and_clean_citations)
   │   ├─► Scan generated text for citation markers: [1], [2], etc.
   │   ├─► Cross-reference markers with retrieved Top 6 candidate map
   │   ├─► Strip hallucinated citation markers (e.g. model outputting [7] when only 6 exist)
   │   └─► Compile CitationCard list: document filename, section title, page number, excerpt
   │
4. Server-Sent Events (SSE) Stream
   │   ├─► Stream tokens in real time: data: {"event": "token", "token": "..."}
   │   ├─► Emit verified citations: data: {"event": "citations", "citations": [...]}
   │   └─► Emit completion event: data: {"event": "done", "usage": {...}}
```

### Pipeline 4: Tenant Quota & Budget Enforcement
```
1. Before generation: Check Organization monthly_token_budget
   │   └─► If tokens_used_this_month >= monthly_token_budget:
   │         Raise QuotaExceededError (HTTP 429 Too Many Requests)
   │
2. After generation: Record UsageEvent
   │   ├─► Atomically increment tokens_used_this_month
   │   └─► Store prompt_tokens, completion_tokens, latency_ms, cost_usd
```

---

## 4. How to Run & Verify the Platform

### Running with Docker Compose (Recommended)
```bash
# 1. Initialize environment
cp .env.example .env

# 2. Start all 7 microservices
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

---

## 5. Automated CI/CD Quality Gates & Testing Architecture

DocIntel enforces automated checks on every push and pull request via GitHub Actions (`.github/workflows/ci.yml`):

1. **Code Quality (Ruff & Mypy)**:
   - Zero lint errors, strict import sorting (`isort`), and clean formatting across all 46 Python files.
   ```bash
   ruff check backend/app backend/tests --config backend/pyproject.toml
   ruff format --check backend/app backend/tests --config backend/pyproject.toml
   ```
2. **Pytest Integration Test Suite**:
   - 24 automated async integration tests covering auth, tenant isolation, chat streaming, citations, and ingestion.
   ```bash
   pytest backend/tests/ -v
   ```
3. **Docker Container Build Validation**:
   - Builds both backend and frontend production container images to guarantee deployment readiness.
4. **RAGAS Retrieval Quality Regression Gate**:
   - Evaluates the 50-question golden benchmark to ensure faithfulness never drops below 0.85:
   ```bash
   python eval/run_eval.py --version v3 --ci-gate --min-faithfulness 0.85
   ```
