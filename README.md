# DocIntel — Multi-Tenant Enterprise Document Intelligence Platform

> **Production-grade, security-hardened RAG platform serving cited, page-level answers over enterprise documents with JWT token rotation/revocation, RBAC, PostgreSQL + pgvector hybrid retrieval, Langfuse v4 tracing, per-tenant cost controls, and automated CI quality gates.**

[![CI / CD Pipeline](https://github.com/anuj-kumar-04/DocIntel-Multi-Tenant-Enterprise-Document-Intelligence-Platform--RAG/actions/workflows/ci.yml/badge.svg)](https://github.com/anuj-kumar-04/DocIntel-Multi-Tenant-Enterprise-Document-Intelligence-Platform--RAG/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791.svg)](https://github.com/pgvector/pgvector)
[![Next.js 15](https://img.shields.io/badge/Next.js-15%20(React%2019)-black.svg)](https://nextjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 1. System Architecture

```text
                             ┌──────────────────────────┐
                             │  Next.js 15 Frontend     │
                             │ (React 19, TS, Tailwind) │
                             │ streaming chat + upload  │
                             └────────────┬─────────────┘
                                          │ HTTPS / SSE
                             ┌────────────▼─────────────┐
                             │     Nginx (Prod Proxy)   │
                             │ TLS, auth rate limit,    │
                             │ headers, gzip, SSE proxy │
                             └────────────┬─────────────┘
                                          │
         ┌────────────────────────────────▼────────────────────────────────┐
         │                    FastAPI (Async Python 3.12)                  │
         │  /auth  /documents  /chat  /admin  /health  /metrics            │
         │  JWT JTI revocation · RBAC · SlowAPI · Security headers · Audit │
         └───┬──────────────┬───────────────┬──────────────┬───────────────┘
             │              │               │              │
             │ enqueue      │ read/write    │ retrieve     │ LLM call + PII mask
             ▼              ▼               ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌─────────────┐  ┌──────────────┐
     │   Redis    │  │ PostgreSQL │  │  pgvector   │  │   LiteLLM    │
     │ queue +    │  │ users,orgs │  │ embeddings  │  │   router     │
     │ sem. cache │  │ docs,chats │  │ + BM25 (tsv)│  │ Groq/Gemini/ │
     │ + lockout  │  │ + auditlog │  │ + RLS ctx   │  │ OpenAI+local │
     └─────┬──────┘  └────────────┘  └─────────────┘  └──────┬───────┘
           │                                                 │
           ▼                                           ┌─────▼──────┐
    ┌──────────────────────────┐                       │ Langfuse v4│
    │   Celery Workers         │                       │ OTel trace │
    │ 1. download from S3      │                       └────────────┘
    │ 2. parse layout & tables │
    │ 3. chunk (layout-aware)  │                       ┌────────────┐
    │ 4. embed (bge-small 384d)│                       │ Prometheus │
    │ 5. upsert to pgvector    │                       │ + Grafana  │
    └──────────┬───────────────┘                       └────────────┘
               │
               ▼
       ┌───────────────┐
       │ S3 / SeaweedFS│  raw file storage (or GCS HMAC S3 in GCP prod)
       └───────────────┘
```

---

## 2. Repository & Project Directory Structure

```text
├── .agents/skills/langfuse/     # Installed Langfuse AI observability & eval skill
├── .github/workflows/ci.yml     # CI/CD: Ruff, Pytest (34 tests), Docker builds, Eval Gate
├── backend/
│   ├── alembic/                 # Database migrations (PostgreSQL + pgvector schema)
│   ├── app/
│   │   ├── api/v1/              # FastAPI REST endpoints & route controllers
│   │   │   ├── admin.py         # Tenant usage, budgets, member invites/removal, audit logs
│   │   │   ├── auth.py          # JWT register, login, refresh rotation, logout & /me
│   │   │   ├── chat.py          # SSE token streaming, BOLA checks & conversational RAG
│   │   │   ├── documents.py     # Magic-byte validated upload, status tracking & delete
│   │   │   ├── health.py        # Liveness & leak-free readiness probes
│   │   │   └── router.py        # Centralized API v1 router aggregator
│   │   ├── core/                # System infrastructure & security controls
│   │   │   ├── errors.py        # Standardized HTTP domain exceptions
│   │   │   ├── logging.py       # Structured JSON request-ID logging
│   │   │   ├── rate_limit.py    # Tenant/IP SlowAPI rate limiting (Redis-backed)
│   │   │   ├── security.py      # BCrypt hashing, JWT JTI revocation & login lockout
│   │   │   └── tracing.py       # Langfuse v4 OpenTelemetry tracing & span hierarchy
│   │   ├── models/              # SQLAlchemy 2.0 async ORM models
│   │   │   ├── audit.py         # Immutable tenant security AuditLog table
│   │   │   ├── base.py          # Declarative Base metadata & UTC TimestampMixin
│   │   │   ├── chat.py          # Conversation and Message entities
│   │   │   ├── chunk.py         # Document chunks (Vector(384) HNSW + TSVECTOR GIN)
│   │   │   ├── document.py      # Document metadata, processing status & SHA-256 hashes
│   │   │   ├── org.py           # Multi-tenant organizations & monthly token quotas
│   │   │   ├── usage.py         # Token usage & dollar spend audit history
│   │   │   └── user.py          # User accounts and RBAC roles (Owner/Admin/Member)
│   │   ├── schemas/             # Pydantic v2 validation DTOs (strict email/password checks)
│   │   ├── scripts/             # reindex_embeddings.py & seed.py operational scripts
│   │   ├── services/            # Core business, RAG & security services
│   │   │   ├── audit.py         # Security audit logging & querying service
│   │   │   ├── auth_service.py  # Auth, RBAC privilege guards, lockout & offboarding
│   │   │   ├── budget.py        # Monthly quota governance & atomic token tracking
│   │   │   ├── cache.py         # Tenant-isolated Redis semantic cache (>0.97 cosine)
│   │   │   ├── chunking.py      # LayoutChunker (section-aware, table preservation)
│   │   │   ├── embeddings.py    # fastembed / SentenceTransformer (384d) + fallback
│   │   │   ├── generation.py    # LiteLLM cascade router, XML fencing & citation verifier
│   │   │   ├── guardrails.py    # Prompt-injection detection & Luhn/PII redaction
│   │   │   ├── parsing.py       # PyMuPDF / python-docx / openpyxl layout parser
│   │   │   ├── retrieval.py     # Hybrid search (pgvector + BM25 + RRF + Cross-Encoder)
│   │   │   └── storage.py       # S3 / SeaweedFS storage with traversal-guarded local fallback
│   │   ├── static/index.html    # Standalone embedded browser UI (non-production)
│   │   ├── workers/             # Celery worker app & async document ingestion tasks
│   │   ├── config.py            # Production-validated Pydantic BaseSettings
│   │   ├── deps.py              # AsyncSession, JWT revocation check & Postgres RLS context
│   │   └── main.py              # App factory, security headers, CORS, SlowAPI & Prometheus
│   ├── tests/                   # 34 automated pytest tests across 7 test suites
│   │   ├── conftest.py          # Async PostgreSQL test engine & dual-tenant fixtures
│   │   ├── test_auth.py         # Auth, registration, RBAC & member offboarding tests (8)
│   │   ├── test_chat.py         # Chat endpoints, SSE streaming & budget enforcement (3)
│   │   ├── test_citations.py    # Citation extraction & hallucination stripping (4)
│   │   ├── test_ingestion.py    # Upload, idempotency, chunking & layout tests (4)
│   │   ├── test_retrieval.py    # Hybrid search, BM25, RRF fusion & semantic cache (5)
│   │   ├── test_security.py     # Headers, magic bytes, BOLA, lockout, guardrails & audit (9)
│   │   └── test_tenant_isolation.py # Zero-leak cross-tenant query isolation test (1)
│   ├── Dockerfile               # Production multi-stage non-root backend container
│   ├── pyproject.toml           # Ruff, Mypy & Pytest configuration
│   └── requirements.txt         # Backend Python dependencies
├── frontend/                    # Next.js 15 / React 19 Enterprise Web Application
│   ├── app/                     # App Router pages ((auth)/login, (app)/chat, documents, admin)
│   ├── components/              # Navbar, ChatStream, CitationCard, UploadDropzone
│   ├── lib/                     # api.ts & useSSE.ts (relative/same-origin Nginx ready)
│   ├── Dockerfile               # Node.js 20 Alpine multi-stage build (with NEXT_PUBLIC args)
│   └── package.json             # Next.js 15, React 19, Tailwind CSS, lucide-react
├── eval/                        # Golden Benchmark Evaluation Suite
│   ├── golden_set.jsonl         # 50 enterprise benchmark questions with expected pages
│   └── run_eval.py              # Benchmark runner & CI faithfulness regression gate
├── deploy/gcp/                  # Google Cloud Compute Engine deployment automation
│   ├── deploy.sh                # Automated Ubuntu Docker, UFW, .env & Certbot SSL setup
│   └── README.md                # GCP firewall, upload & GCS storage guide
├── infra/
│   ├── grafana/                 # Provisioned metrics dashboards
│   ├── nginx/                   # Hardened Nginx reverse proxy + TLS SSL template
│   ├── postgres/rls_policies.sql# Optional PostgreSQL Row-Level Security SQL policies
│   └── prometheus/              # Prometheus scrape configuration
├── ARCHITECTURE.md              # Architectural Decision Records (ADRs) & Interview Script
├── EVALUATION.md                # Retrieval & generation benchmark analysis
├── PROJECT_EXPLAINED.md         # Deep-dive system walkthrough
├── Project1_Blueprint_DocIntel (1).md # Full architectural blueprint (synced to codebase)
├── Project 1 blueprint.docx     # Formatted Microsoft Word blueprint export
├── docker-compose.yml           # 8-container local development & observability stack
├── docker-compose.prod.yml      # 7-container hardened production stack (+ Nginx, - dev ports)
├── .env.example                 # Local development environment template
├── .env.prod.example            # Production / GCP environment template
└── Makefile                     # Developer shortcuts (up, down, test, lint, seed, eval)
```

---

## 3. Evaluation Results (50-Question Golden Benchmark)

Baseline comparison recorded in [`EVALUATION.md`](EVALUATION.md) via [`eval/run_eval.py`](eval/run_eval.py) *(synthetic deterministic benchmark over the 50-question golden set; latest CI gate verification scored `0.943` faithfulness $\ge 0.85$)*:

| Pipeline Configuration | Faithfulness | Answer Relevancy | Hit@5 | MRR | Refusal Accuracy | p95 Latency | Cost / Query ($) |
|---|---|---|---|---|---|---|---|
| **v1 Naive Baseline** (Dense-only top-5) | 0.72 | 0.78 | 0.70 | 0.56 | 0.40 | 0.44s | $0.0031 |
| **v2 Hybrid + Multi-Query** (+ BM25 + RRF) | 0.82 | 0.86 | 0.84 | 0.72 | 1.00 | 0.61s | $0.0044 |
| **v3 Full Stack** (+ Cross-Encoder Re-rank + Citations) | **0.90** | **0.91** | **0.92** | **0.84** | **1.00** | 0.78s | $0.0048 |

---

## 4. Key Capabilities & Security Highlights

- [x] **Zero-Leak Multi-Tenancy + RLS Context**: Denormalized `org_id` on chunks enforced in SQL `WHERE` clauses, token-to-DB `org_id` validation, same-org BOLA conversation ownership checks (`user_id`), and PostgreSQL `app.current_org_id` RLS binding.
- [x] **Defense-in-Depth Auth & Access Governance**: SlowAPI global & endpoint rate limiting, Redis brute-force account lockout (`5` failures → `15` min), JWT `jti` blacklisting (`/auth/logout`), single-use refresh token rotation, instant session revocation on member deletion, and invite privilege-escalation blocks.
- [x] **Document Armor & GenAI Guardrails**: Binary magic-byte signature validation, 100 MB Zip-bomb protection, path-traversal filename sanitization, prompt-injection detection, `<retrieved_context>` XML isolation fences, and Luhn-validated PII/API-key masking prior to cloud LLM calls.
- [x] **Immutable Security Audit Trail**: Tenant-scoped `audit_logs` table recording auth, offboarding, budget, and document events (`GET /api/v1/admin/audit-logs`).
- [x] **Layout-Aware Chunking & Section-Linked Hybrid Retrieval**: Preserves tables whole as Markdown; combines `pgvector` HNSW (`BAAI/bge-small-en-v1.5`, 384d) + Postgres `tsvector` (`section_title || content_tsv`) via RRF ($k=60$) and `BAAI/bge-reranker-v2-m3`.
- [x] **Verified Citations & Resilient LLM Waterfall**: Streams SSE tokens via LiteLLM (`Groq → Gemini → OpenAI → Local Grounded Engine`), validates `[1]` citation indices, and purges unsupported markers.
- [x] **Langfuse v4 + Prometheus + Grafana Observability**: Typed OpenTelemetry spans (`SPAN` → `RETRIEVER` → `GENERATION`) linked to user/session/tenant attributes alongside Prometheus & Grafana dashboards.
- [x] **34 Passing Automated Tests & CI Gate**: Full Ruff linting/formatting, 34 pytest integration & security tests, Docker container builds, and retrieval regression gating.

---

## 5. Quick Start

### Option A: Local Development Stack (`docker-compose.yml` — 8 Containers)

```bash
# 1. Configure local environment
cp .env.example .env

# 2. Build & start db, redis, minio (seaweedfs), api, worker, prometheus, grafana, frontend
docker compose up -d --build

# 3. Seed demo organizations, users & sample chunks
docker compose exec api python app/scripts/seed.py
```

* **Next.js Web UI**: [http://localhost:3000](http://localhost:3000) (or embedded dev UI at [http://localhost:8000/app/index.html](http://localhost:8000/app/index.html))
* **Interactive Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
* **Prometheus Metrics**: [http://localhost:9090](http://localhost:9090)
* **Grafana Dashboards**: [http://localhost:3002](http://localhost:3002) (`admin` / `admin`)
* **SeaweedFS S3 Endpoint**: `http://localhost:9000`

### Option B: Hardened Production / Google Cloud (`docker-compose.prod.yml`)

Use [`deploy/gcp/deploy.sh`](deploy/gcp/deploy.sh) on an Ubuntu Compute Engine VM behind Nginx (ports `80`/`443` only, Swagger `/docs` disabled, demo logins hidden, Gunicorn 4 workers):

```bash
chmod +x deploy/gcp/deploy.sh
./deploy/gcp/deploy.sh your-domain.com admin@your-domain.com
```

See [`deploy/gcp/README.md`](deploy/gcp/README.md) and [`.env.prod.example`](.env.prod.example) for complete GCP deployment instructions.

---

## 6. Pre-Seeded Development Accounts

*(Available locally after running `seed.py`; demo credential helpers are automatically disabled in production builds unless `NEXT_PUBLIC_DEMO_MODE=true` is explicitly enabled.)*

| Tenant Organization | User Email | Password | Role | Description |
|---|---|---|---|---|
| **Acme Corporation** | `admin@acme.com` | `Password123!` | Owner | Full org, member, audit-log & budget governance |
| **Acme Corporation** | `analyst@acme.com` | `Password123!` | Member | Standard user (blocked from `/admin` routes) |
| **Zephyr Industries** | `admin@zephyr.com` | `Password123!` | Owner | Second isolated tenant for cross-org verification |

---

## 7. Running Tests & Evaluation

```bash
# Run full automated test suite inside API container (34 tests across 7 files)
docker compose exec api pytest tests/ -v

# Run security hardening test suite specifically
docker compose exec api pytest tests/test_security.py -v

# Run CI quality checks
ruff check backend/app backend/tests --config backend/pyproject.toml
ruff format --check backend/app backend/tests --config backend/pyproject.toml

# Run 50-question evaluation benchmark & CI gate (Faithfulness >= 0.85)
python eval/run_eval.py --version all
python eval/run_eval.py --version v3 --ci-gate --min-faithfulness 0.85
```
