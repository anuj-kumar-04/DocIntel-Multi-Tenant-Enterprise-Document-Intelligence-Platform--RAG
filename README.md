# DocIntel — Multi-Tenant Enterprise Document Intelligence Platform

> **Production-grade RAG platform serving cited, page-level answers over enterprise documents with JWT auth, role-based access control, SQL-enforced multi-tenancy, and published RAGAS evaluation numbers.**

[![CI / CD Pipeline](https://github.com/organization/docintel/actions/workflows/ci.yml/badge.svg)](https://github.com/organization/docintel/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791.svg)](https://github.com/pgvector/pgvector)
[![Next.js 15](https://img.shields.io/badge/Next.js-15%20(React%2019)-black.svg)](https://nextjs.org/)

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
    └──────────┬───────────────┘                        │ Prometheus │
               │                                        │ + Grafana  │
               ▼                                        └────────────┘
       ┌───────────────┐
       │  S3 / MinIO   │  raw file storage
       └───────────────┘
```

---

## 2. Evaluation Results (Hand-Crafted 50-Question Golden Benchmark)

| Pipeline Configuration | Faithfulness (RAGAS) | Answer Relevancy | Hit@5 | MRR | Refusal Accuracy | p95 Latency | Cost / Query ($) |
|---|---|---|---|---|---|---|---|
| **v1 Naive Baseline** (Dense-only top-5) | 0.72 | 0.78 | 0.70 | 0.56 | 0.40 | 0.44s | $0.0031 |
| **v2 Hybrid + Multi-Query** (+ BM25 + RRF) | 0.82 | 0.86 | 0.84 | 0.72 | 1.00 | 0.61s | $0.0044 |
| **v3 Full Stack** (+ Cross-Encoder Re-rank + Citations) | **0.90** | **0.91** | **0.92** | **0.84** | **1.00** | 0.78s | $0.0048 |

Detailed metric analysis and regression gate specifications are documented in [EVALUATION.md](file:///d:/PROJECTS/DocIntel%20%E2%80%94%20Multi-Tenant%20Enterprise%20Document%20Intelligence%20Platform/EVALUATION.md).

---

## 3. Credibility Checklist

- [x] **Zero-Leak Multi-Tenancy**: Denormalized `org_id` on chunks enforced in every SQL `WHERE` clause.
- [x] **40+ Automated Tests**: Comprehensive pytest suite covering auth, RBAC, ingestion, retrieval, and tenant isolation.
- [x] **Layout-Aware Chunking & Section Linking**: Preserves tables whole as markdown; concatenates section titles with content tsvectors to resolve cross-page table splits.
- [x] **Bidirectional Unicode Sanitizer**: Automatically cleans invisible control markers (`\u202d`, `\u202c`, zero-width spaces) from Google Docs/Word PDF exports.
- [x] **Verified Citations**: Emits inline `[1]`, `[2]` chips with document, section, and page source snippets; purges hallucinated citations.
- [x] **Multi-Model Cascade**: Ultra-low latency streaming via Groq Qwen/Llama with automatic failover to Gemini Flash, OpenAI, and local grounded extraction.
- [x] **Semantic Caching**: Sub-millisecond Redis vector cache for cosine similarity $>0.97$.
- [x] **Token Budget Governance**: Monthly quota enforcement returning HTTP 429 when exhausted.
- [x] **CI/CD Quality Gate**: Ruff linting, Mypy type-checking, test suite with coverage, and RAGAS regression gate.

---

## 4. Quick Start

### Option A: Complete Microservices Stack with Docker Compose

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

## 5. Pre-Seeded Demonstration Accounts

| Tenant Organization | User Email | Password | Role | Description |
|---|---|---|---|---|
| **Acme Corporation** | `admin@acme.com` | `Password123!` | Owner | Access to Q4 Financials & Security Policy |
| **Acme Corporation** | `analyst@acme.com` | `Password123!` | Member | Standard member (cannot access admin endpoints) |
| **Zephyr Industries** | `admin@zephyr.com` | `Password123!` | Owner | Owns confidential proprietary engine margin analysis |

---

## 6. Running Tests & Evaluation

```bash
# Run full automated test suite with coverage
pytest backend/tests/ -v

# Run the strict multi-tenant isolation test
pytest backend/tests/test_tenant_isolation.py -v

# Run 50-question golden evaluation benchmark across v1, v2, and v3
python eval/run_eval.py --version all
```
