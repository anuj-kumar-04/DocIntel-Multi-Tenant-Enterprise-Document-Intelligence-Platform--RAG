# DocIntel — Multi-Tenant Enterprise Document Intelligence Platform

> **Production-grade RAG platform serving cited, page-level answers over enterprise documents with JWT auth, role-based access control, SQL-enforced multi-tenancy, and published RAGAS evaluation numbers.**

[![CI / CD Pipeline](https://github.com/anuj-kumar-04/DocIntel-Multi-Tenant-Enterprise-Document-Intelligence-Platform--RAG/actions/workflows/ci.yml/badge.svg)](https://github.com/anuj-kumar-04/DocIntel-Multi-Tenant-Enterprise-Document-Intelligence-Platform--RAG/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791.svg)](https://github.com/pgvector/pgvector)
[![Next.js 15](https://img.shields.io/badge/Next.js-15%20(React%2019)-black.svg)](https://nextjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 1. System Architecture

```
                             ┌──────────────────────────┐
                             │  Next.js 15 Frontend     │
                             │  (TS, Tailwind, shadcn)  │
                             │  streaming chat + upload │
                             └────────────┬─────────────┘
                                          │ HTTPS / SSE
                             ┌────────────▼─────────────┐
                             │        Nginx             │
                             │  TLS, routing, gzip      │
                             └────────────┬─────────────┘
                                          │
         ┌────────────────────────────────▼────────────────────────────────┐
         │                    FastAPI (Async Python 3.12)                  │
         │  /auth  /documents  /chat  /admin  /health  /metrics            │
         │  JWT middleware · RBAC · rate limit · request-id logging        │
         └───┬──────────────┬───────────────┬──────────────┬───────────────┘
             │              │               │              │
             │ enqueue      │ read/write    │ retrieve     │ LLM call
             ▼              ▼               ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌─────────────┐  ┌──────────────┐
     │   Redis    │  │ PostgreSQL │  │  pgvector    │  │  LiteLLM     │
     │ queue +    │  │ users,orgs │  │  embeddings  │  │  router      │
     │ sem. cache │  │ docs,chats │  │  + BM25 (tsv)│  │ Groq/OpenAI/ │
     └─────┬──────┘  └────────────┘  └─────────────┘  │ Gemini +     │
           │                                           │ fallback     │
           ▼                                           └──────┬───────┘
    ┌──────────────────────────┐                              │
    │   Celery Workers         │                        ┌─────▼──────┐
    │ 1. download from S3      │                        │  Langfuse  │
    │ 2. parse layout & tables │                        │  tracing   │
    │ 3. chunk (layout-aware)  │                        └────────────┘
    │ 4. embed in batches      │
    │ 5. upsert to pgvector    │                        ┌────────────┐
    │ 6. resilient storage     │                        │ Prometheus │
    └──────────┬───────────────┘                        │ + Grafana  │
               │                                        └────────────┘
               ▼
       ┌───────────────┐
       │  S3 / MinIO   │  raw file storage (with local fallback)
       └───────────────┘
```

---

## 2. Repository & Project Directory Structure

```
├── .github/
│   └── workflows/
│       └── ci.yml               # Production CI/CD pipeline (Ruff, Pytest, Docker, RAGAS Gate)
├── backend/
│   ├── alembic/                 # Database migrations (PostgreSQL + pgvector schema)
│   ├── app/
│   │   ├── api/v1/              # FastAPI REST endpoints & route controllers
│   │   │   ├── admin.py         # Tenant management & organization metrics
│   │   │   ├── auth.py          # JWT login, registration & user profiling
│   │   │   ├── chat.py          # SSE token streaming & conversational RAG endpoint
│   │   │   ├── documents.py     # Multi-format document upload & status tracking
│   │   │   ├── health.py        # Kubernetes liveness & readiness health checks
│   │   │   └── router.py        # Centralized API v1 route aggregator
│   │   ├── core/                # System infrastructure & middleware
│   │   │   ├── errors.py        # Standardized enterprise HTTP exceptions
│   │   │   ├── logging.py       # Structured JSON request-ID logging
│   │   │   ├── rate_limit.py    # IP/User-based rate limiting (SlowAPI)
│   │   │   ├── security.py      # BCrypt password hashing & JWT token management
│   │   │   └── tracing.py       # Langfuse distributed tracing & span management
│   │   ├── models/              # SQLAlchemy 2.0 async database models
│   │   │   ├── base.py          # Declarative Base metadata
│   │   │   ├── chat.py          # ChatSession and ChatMessage entities
│   │   │   ├── chunk.py         # Document chunks with pgvector embeddings & BM25 tsv
│   │   │   ├── document.py      # Document metadata, processing statuses & SHA-256 hashes
│   │   │   ├── org.py           # Multi-tenant organizations & monthly token quotas
│   │   │   ├── usage.py         # Token usage audit logs & event history
│   │   │   └── user.py          # User accounts and RBAC roles (Owner/Admin/Member)
│   │   ├── schemas/             # Pydantic v2 validation models & DTOs
│   │   │   ├── admin.py         # Tenant governance & usage response schemas
│   │   │   ├── auth.py          # Auth requests, user responses & token schemas
│   │   │   ├── chat.py          # Chat message inputs, citations & streaming schemas
│   │   │   └── document.py      # Document upload & listing schemas
│   │   ├── scripts/             # Operational utility scripts
│   │   │   ├── reindex_embeddings.py # Vector embedding backfill & migration utility
│   │   │   └── seed.py          # Seeds demo organizations, users & realistic documents
│   │   ├── services/            # Core business & algorithmic intelligence
│   │   │   ├── auth_service.py  # User authentication & permission checks
│   │   │   ├── budget.py        # Monthly quota governance & atomic token tracking
│   │   │   ├── cache.py         # Redis semantic vector cache (>0.97 similarity)
│   │   │   ├── chunking.py      # LayoutChunker (section-aware, table preservation)
│   │   │   ├── embeddings.py    # Embedding generator with batching & normalized fallbacks
│   │   │   ├── generation.py    # LLM cascade router & citation verification engine
│   │   │   ├── parsing.py       # PyMuPDF / docx / openpyxl layout parser + unicode sanitizer
│   │   │   ├── retrieval.py     # Hybrid search (pgvector + BM25 + RRF + Cross-Encoder)
│   │   │   └── storage.py       # S3 / SeaweedFS / MinIO storage with resilient local fallback
│   │   ├── static/              # Standalone embedded executive web interface
│   │   │   └── index.html       # Zero-dependency, modern responsive browser UI
│   │   ├── workers/             # Asynchronous background task workers
│   │   │   ├── celery_app.py    # Celery instance configuration with Redis broker
│   │   │   └── tasks.py         # Document parsing, chunking & vector indexing pipeline
│   │   ├── config.py            # Pydantic BaseSettings environment configuration
│   │   ├── deps.py              # FastAPI dependency injection (AsyncSession, User, DB)
│   │   └── main.py              # Application lifespan, CORS, Prometheus instrumentation
│   ├── tests/                   # Pytest test suite (24 automated tests, 100% passing)
│   │   ├── conftest.py          # Async PostgreSQL test engine, client & tenant fixtures
│   │   ├── test_auth.py         # Auth, registration, and RBAC tests
│   │   ├── test_chat.py         # Chat endpoints, streaming & quota enforcement
│   │   ├── test_citations.py    # Citation extraction, validation & hallucination stripping
│   │   ├── test_ingestion.py    # File upload, idempotency, chunking & layout tests
│   │   ├── test_retrieval.py    # Hybrid search, BM25, RRF fusion & semantic cache
│   │   └── test_tenant_isolation.py # Cryptographic zero-leak cross-tenant query tests
│   ├── Dockerfile               # Production multi-stage backend container
│   ├── pyproject.toml           # Ruff, Mypy & Pytest tooling configuration
│   └── requirements.txt         # Pinned backend dependencies
├── frontend/                    # Next.js 15 enterprise web application
│   ├── app/                     # App router pages, layouts & providers
│   ├── components/              # React components (ChatDrawer, FileUploader, CitationCard)
│   ├── lib/                     # API client, SSE stream parsers & auth utilities
│   ├── public/                  # Static assets & icons
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

## 3. Evaluation Results (Hand-Crafted 50-Question Golden Benchmark)

| Pipeline Configuration | Faithfulness (RAGAS) | Answer Relevancy | Hit@5 | MRR | Refusal Accuracy | p95 Latency | Cost / Query ($) |
|---|---|---|---|---|---|---|---|
| **v1 Naive Baseline** (Dense-only top-5) | 0.72 | 0.78 | 0.70 | 0.56 | 0.40 | 0.44s | $0.0031 |
| **v2 Hybrid + Multi-Query** (+ BM25 + RRF) | 0.82 | 0.86 | 0.84 | 0.72 | 1.00 | 0.61s | $0.0044 |
| **v3 Full Stack** (+ Cross-Encoder Re-rank + Citations) | **0.90** | **0.91** | **0.92** | **0.84** | **1.00** | 0.78s | $0.0048 |

Detailed metric analysis and regression gate specifications are documented in [EVALUATION.md](file:///d:/PROJECTS/DocIntel%20%E2%80%94%20Multi-Tenant%20Enterprise%20Document%20Intelligence%20Platform/EVALUATION.md).

---

## 4. Key Capabilities & Technical Highlights

- [x] **Zero-Leak Multi-Tenancy**: Denormalized `org_id` on chunks enforced in every SQL `WHERE` clause.
- [x] **Automated Test Suite**: 24 comprehensive pytest integration tests covering auth, RBAC, ingestion, retrieval, and tenant isolation (100% passing).
- [x] **Layout-Aware Chunking & Section Linking**: Preserves tables whole as markdown; concatenates section titles with content tsvectors to resolve cross-page table splits.
- [x] **Bidirectional Unicode Sanitizer**: Automatically cleans invisible control markers (`\u202d`, `\u202c`, zero-width spaces) from Google Docs/Word PDF exports.
- [x] **Verified Citations**: Emits inline `[1]`, `[2]` chips with document, section, and page source snippets; purges hallucinated citations.
- [x] **Multi-Model Cascade**: Ultra-low latency streaming via Groq Qwen/Llama with automatic failover to Gemini Flash, OpenAI, and local grounded extraction.
- [x] **Semantic Caching**: Sub-millisecond Redis vector cache for cosine similarity $>0.97$.
- [x] **Token Budget Governance**: Monthly quota enforcement returning HTTP 429 when exhausted.
- [x] **CI/CD Quality Gate**: Ruff linting, Mypy type-checking, test suite with coverage, and automated RAGAS regression gate.

---

## 5. Quick Start

### Option A: Complete Microservices Stack with Docker Compose (Recommended)

```bash
# 1. Clone repository & configure environment
cp .env.example .env

# 2. Spin up all 7 microservices
docker compose up -d

# 3. Apply database migrations & seed initial demo data
docker compose exec api alembic upgrade head
docker compose exec api python app/scripts/seed.py
```

- **Frontend Executive UI**: [http://localhost:3000](http://localhost:3000) (or [http://localhost:8000/app/index.html](http://localhost:8000/app/index.html))
- **Interactive OpenAPI Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Prometheus Metrics**: [http://localhost:9090](http://localhost:9090)
- **Grafana Dashboards**: [http://localhost:3002](http://localhost:3002) (Login: `admin` / `admin`)
- **MinIO Console**: [http://localhost:9001](http://localhost:9001) (Login: `minioadmin` / `minioadmin`)

---

### Option B: Local Python Development Run

```bash
# 1. Install dependencies
cd backend
python -m pip install -r requirements.txt

# 2. Run database migrations or seed data
python app/scripts/seed.py

# 3. Launch FastAPI development server
uvicorn app.main:app --reload --port 8000
```

Open your browser to: **[http://localhost:8000/app/index.html](http://localhost:8000/app/index.html)**

---

## 6. Pre-Seeded Demonstration Accounts

| Tenant Organization | User Email | Password | Role | Description |
|---|---|---|---|---|
| **Acme Corporation** | `admin@acme.com` | `Password123!` | Owner | Access to Q4 Financials & Security Policy |
| **Acme Corporation** | `analyst@acme.com` | `Password123!` | Member | Standard member (cannot access admin endpoints) |
| **Zephyr Industries** | `admin@zephyr.com` | `Password123!` | Owner | Owns confidential proprietary engine margin analysis |

---

## 7. Running Tests & Evaluation

```bash
# Run full automated test suite (24 tests)
pytest backend/tests/ -v

# Run the strict multi-tenant isolation test
pytest backend/tests/test_tenant_isolation.py -v

# Run 50-question golden evaluation benchmark across v1, v2, and v3
python eval/run_eval.py --version all

# Run CI Gate validation (checks Faithfulness >= 0.85)
python eval/run_eval.py --version v3 --ci-gate --min-faithfulness 0.85
```
