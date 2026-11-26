# PROJECT 1 BLUEPRINT
# "DocIntel" — Multi-Tenant Enterprise Document Intelligence Platform

**Flagship Project Blueprint — Synchronized with the Implemented Codebase, Security Architecture, and Google Cloud Production Deployment.**

Target outcome: a live, Dockerized, authenticated, security-hardened, and monitored RAG platform with published evaluation benchmarks — the kind of system that lets you walk an interviewer step-by-step through real trade-offs, multi-tenant defense-in-depth, and verifiable engineering metrics.

---

# PART 0 — What DocIntel Solves and Why

## 0.1 The Product in One Paragraph

An organization signs up via `/api/v1/auth/register`. Team members upload PDF, DOCX, XLSX, TXT, and Markdown files (annual reports, contracts, policy manuals, financial sheets). Uploads undergo MIME, magic-byte, Zip-bomb, and SHA-256 deduplication checks before streaming to S3-compatible storage and running asynchronously on Celery workers. Any team member can ask natural-language questions over private SSE-streamed chat sessions and receive grounded answers with **inline citations `[1]`, `[2]` mapped to exact documents, sections, and page numbers**. Tenant isolation is enforced in SQL, JWT claims, Redis cache keys, and PostgreSQL RLS session bindings. Admins govern member access, monthly token budgets, and immutable security audit logs, while every request is traced in Langfuse v4, metered in Prometheus/Grafana, and gated in CI.

## 0.2 Engineering Questions This Project Answers

| Interview Question | Implemented DocIntel Feature |
|---|---|
| "Have you built a real backend?" | Async FastAPI + Pydantic v2 + PostgreSQL 16 + Alembic + JWT rotation/revocation + RBAC |
| "How do you handle long-running work?" | Celery workers + Redis broker + exponential backoff retries + `/status` polling |
| "Can you do more than cosine similarity?" | Hybrid Dense (`pgvector` HNSW) + Sparse (`tsvector` BM25) + RRF ($k=60$) + `bge-reranker-v2-m3` |
| "How do you evaluate RAG quality?" | 50-question golden dataset + `eval/run_eval.py` across v1/v2/v3 + CI faithfulness gate ($\ge 0.85$) |
| "How do you control LLM cost & resilience?" | LiteLLM router cascade (`Groq → Gemini → OpenAI → Local Engine`), Redis semantic cache, monthly budgets |
| "How do you enforce multi-tenancy & security?" | SQL `org_id` + RLS `set_config`, same-org conversation BOLA checks, magic-byte validation, PII redaction, audit logs |
| "Can you deploy and operate it?" | Dual `docker-compose` (Dev + GCP Prod with Nginx TLS), Prometheus/Grafana, Langfuse v4 OTel traces, JSON logs |
| "Do you test your code?" | **34 pytest integration & security tests** + GitHub Actions CI (Ruff + Pytest + Docker + RAG Gate) |

## 0.3 Production Readiness Checklist

- [x] Runs locally via `docker compose up -d` and in production via `docker compose -f docker-compose.prod.yml up -d`
- [x] `README.md`, `PROJECT_EXPLAINED.md`, `ARCHITECTURE.md`, and `EVALUATION.md` synchronized with codebase
- [x] **34 automated pytest tests** passing across 7 suites (`test_auth`, `test_chat`, `test_citations`, `test_ingestion`, `test_retrieval`, `test_security`, `test_tenant_isolation`)
- [x] Security hardened (HTTP headers, SlowAPI limits, Redis login lockout, JWT `jti` revocation, magic bytes, prompt-injection & PII guardrails, immutable `audit_logs`, fail-fast prod secrets)
- [x] `.env.example`, `.env.prod.example`, and automated Google Cloud deploy script ([`deploy/gcp/deploy.sh`](deploy/gcp/deploy.sh))

---

# PART 1 — Architecture

## 1.1 System Diagram

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

## 1.2 The RAG Query & Security Pipeline

```text
User question + chat history + Bearer JWT (verified JTI & RLS org context)
   │
   ├─▶ [0] Security checks: SlowAPI (30/min), prompt-injection detector, monthly token budget gate
   │
   ├─▶ [1] Tenant-isolated Redis Semantic Cache (cosine > 0.97) ──hit──▶ stream cached response
   │
   ├─▶ [2] QueryRewriter: coreference resolution for follow-ups → standalone query
   │
   ├─▶ [3] Multi-query expansion: up to 3 query variations for broader recall
   │
   ├─▶ [4] Sequential AsyncSession-safe hybrid search per query (WHERE org_id = :org_id):
   │         • Dense:  pgvector HNSW cosine distance, top 20
   │         • Sparse: Postgres ts_rank_cd over (section_title || content_tsv), top 20
   │         └─ fuse with Reciprocal Rank Fusion (k=60) → top 30 unique chunks
   │
   ├─▶ [5] Cross-Encoder Re-ranker (BAAI/bge-reranker-v2-m3 + lexical/table fallback) → top 6
   │
   ├─▶ [6] Context assembly: strip invisible Unicode markers, redact PII/keys, fence in <retrieved_context>
   │
   ├─▶ [7] Generate: strict prompt — answer ONLY from numbered blocks, cite as [1],[2] or refuse
   │
   ├─▶ [8] Post-check: verify every citation index exists; purge hallucinated cite numbers
   │
   └─▶ [9] Stream SSE events + record UsageEvent + flush Langfuse v4 OTel spans (session_id, user_id, org)
```

**Core Architectural Trade-Offs:**
- **Why `pgvector` over dedicated Vector DBs?** Relational entities, ACLs, audit logs, HNSW embeddings, and `TSVECTOR` full-text search live inside one ACID Postgres database—eliminating dual-write sync failures and orphaned tenant vectors on delete.
- **Why RRF ($k=60$) over Score Normalization?** Cosine similarity and Postgres `ts_rank_cd` inhabit incompatible scales; RRF fuses rank order robustly without fragile hyperparameter tuning.
- **Why Custom Services over Black-Box Frameworks?** Direct Python services give full control over table-preserving chunking, AsyncSession concurrency safety, custom citation verification, and offline fallback engines.

## 1.3 Actual Tech Stack Implemented

| Layer | Implementation Choice | Purpose |
|---|---|---|
| **API & Validation** | FastAPI + Pydantic v2 + SlowAPI (async) | High-concurrency REST + SSE streaming + rate limits |
| **Database & Vectors** | PostgreSQL 16 + `pgvector` (HNSW `384d`) + `TSVECTOR` GIN | Single ACID engine for relational + hybrid search + RLS |
| **ORM & Migrations** | SQLAlchemy 2.0 (async) + Alembic | Async sessions (`AsyncSessionLocal`) & schema versioning |
| **Queue & Cache** | Celery + Redis 7 (`redis:7-alpine`) | Non-blocking ingestion, semantic cache, lockouts & JWT revocation |
| **Object Storage** | SeaweedFS S3 (`minio` service) / GCS HMAC in GCP | S3 API via `boto3` + traversal-guarded local fallback |
| **Parsing & Chunking** | `PyMuPDF` (`fitz`), `python-docx`, `openpyxl` + `LayoutChunker` | Extracts Markdown tables & sections (`700` tokens / `100` overlap) |
| **Embeddings & Re-rank** | `BAAI/bge-small-en-v1.5` (`fastembed`/`SentenceTransformer`) + `BAAI/bge-reranker-v2-m3` | Local 384d bi-encoder + cross-encoder precision with offline fallbacks |
| **LLM Gateway** | `LiteLLM` waterfall + Local Grounded Engine | Groq → Gemini → OpenAI → deterministic extractive synthesis |
| **Tracing & Metrics** | **Langfuse v4** OTel + Prometheus + Grafana | `SPAN`/`RETRIEVER`/`GENERATION` traces, latency histograms & dashboards |
| **Frontend** | Next.js 15 + React 19 + TypeScript + Tailwind CSS | SSE streaming chat, citation drawer, vault, team admin & offboarding UI |
| **Security & Auth** | JWT (`jti` + refresh rotation), `bcrypt`, `guardrails.py`, `AuditLog` | End-to-end enterprise defense-in-depth |
| **CI/CD & Eval** | GitHub Actions (Ruff, Pytest 34 tests, Docker, Eval Gate) | Automated quality & faithfulness ($\ge 0.85$) enforcement |
| **Deployment** | `docker-compose.yml` (Dev) & `docker-compose.prod.yml` + Nginx TLS + GCE script | Secure local dev + 1-command Google Cloud Compute Engine launch |

---

# PART 2 — Actual Repository Structure

```text
DocIntel/
├── .agents/skills/langfuse/          # Installed Langfuse AI skill & references
├── .github/workflows/ci.yml          # Ruff, Pytest suite, Docker build, Eval regression gate
├── .env.example                      # Dev environment template
├── .env.prod.example                 # Production / GCP environment template
├── docker-compose.yml                # 8-container local dev stack (incl. Prometheus/Grafana)
├── docker-compose.prod.yml           # 7-container hardened production stack (+ Nginx TLS)
├── Makefile                          # Developer shortcuts (up, down, test, lint, seed, eval)
├── README.md / PROJECT_EXPLAINED.md / ARCHITECTURE.md / EVALUATION.md
│
├── backend/
│   ├── Dockerfile                    # Multi-stage non-root Python 3.12 container
│   ├── pyproject.toml                # Ruff, Mypy & Pytest settings
│   ├── requirements.txt              # Pinned backend packages
│   ├── alembic/                      # Database migrations
│   ├── app/
│   │   ├── main.py                   # App factory, SecurityHeadersMiddleware, SlowAPI, CORS
│   │   ├── config.py                 # Settings + production fail-fast secret validator
│   │   ├── deps.py                   # AsyncSession, JWT revocation check, Postgres RLS context
│   │   ├── api/v1/
│   │   │   ├── auth.py               # register, login, refresh, logout, me
│   │   │   ├── documents.py          # validated upload, list, status, detail, delete
│   │   │   ├── chat.py               # conversations CRUD & SSE /ask with BOLA + guardrails
│   │   │   ├── admin.py              # usage, budget, members invite/delete, audit-logs
│   │   │   ├── health.py             # /health, leak-free /ready
│   │   │   └── router.py             # /api/v1 router registration
│   │   ├── core/                     # errors.py, logging.py, rate_limit.py, security.py, tracing.py
│   │   ├── models/                   # org, user, document, chunk, chat, usage, audit
│   │   ├── schemas/                  # Pydantic v2 DTOs + strict email/password validation
│   │   ├── scripts/                  # seed.py, reindex_embeddings.py
│   │   ├── services/                 # auth_service, audit, budget, cache, chunking, embeddings,
│   │   │                             # generation, guardrails, parsing, retrieval, storage
│   │   ├── static/index.html         # Dev-only standalone web dashboard
│   │   └── workers/                  # celery_app.py, tasks.py
│   └── tests/                        # 34 passing automated pytest tests
│       ├── conftest.py               # Async Postgres test fixtures & two-tenant seed
│       ├── test_auth.py              # Auth, RBAC & member offboarding (8 tests)
│       ├── test_chat.py              # Conversations, SSE & budget 429 enforcement (3 tests)
│       ├── test_citations.py         # Citation matching & hallucination removal (4 tests)
│       ├── test_ingestion.py         # Upload, idempotency, LayoutChunker (4 tests)
│       ├── test_retrieval.py         # Configs, RRF fusion, cache & query rewriter (5 tests)
│       ├── test_security.py          # Headers, magic bytes, BOLA, lockout, guardrails, audit (9 tests)
│       └── test_tenant_isolation.py  # Cross-tenant zero-leak end-to-end test (1 test)
│
├── eval/
│   ├── golden_set.jsonl              # 50 hand-crafted benchmark questions
│   └── run_eval.py                   # v1/v2/v3 evaluation harness & CI regression gate
│
├── frontend/
│   ├── Dockerfile                    # Multi-stage Node 20 container (NEXT_PUBLIC build args)
│   ├── app/                          # (auth)/login, (app)/chat, (app)/documents, (app)/admin
│   ├── components/                   # Navbar, ChatStream, CitationCard, UploadDropzone
│   └── lib/                          # api.ts, useSSE.ts (tracked cleanly in Git)
│
├── deploy/gcp/
│   ├── deploy.sh                     # Automated GCP Ubuntu deployment & Certbot SSL script
│   └── README.md                     # GCE VM setup, firewall rules & upload instructions
│
└── infra/
    ├── nginx/                        # nginx.conf + nginx.ssl.conf.template
    ├── postgres/rls_policies.sql     # Native PostgreSQL Row-Level Security policies
    ├── grafana/ & prometheus/        # Observability provisioning & scrape rules
```

---

# PART 3 — Data Model (Implemented Entities)

```sql
-- Multi-Tenant Core
organizations(id uuid pk, name, slug unique, plan, monthly_token_budget bigint,
              tokens_used_this_month bigint default 0, created_at)

users(id uuid pk, org_id fk->organizations, email unique, hashed_password,
      full_name, role enum('owner','admin','member') default 'member',
      is_active bool, created_at, last_login_at)

-- Document Vault & Hybrid Vector/FTS Index
documents(id uuid pk, org_id fk, uploaded_by fk->users ON DELETE SET NULL, filename, s3_key,
          mime_type, size_bytes, page_count, status enum('queued','parsing','embedding','ready','failed'),
          error_message text null, chunk_count int default 0, content_hash, processed_at, created_at)

chunks(id uuid pk, document_id fk->documents ON DELETE CASCADE, org_id fk->organizations ON DELETE CASCADE,
       content text, content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
       embedding vector(384), page_number int, chunk_index int,
       section_title text null, element_type text, token_count int, created_at)
  INDEX ix_chunks_org_id (org_id)
  INDEX ix_chunks_tsv USING gin (content_tsv)
  INDEX ix_chunks_embedding_hnsw USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)

-- Conversational RAG History
conversations(id uuid pk, org_id fk, user_id fk ON DELETE CASCADE, title, created_at, updated_at)

messages(id uuid pk, conversation_id fk ON DELETE CASCADE, role enum('user','assistant'),
         content text, citations jsonb, prompt_tokens int, completion_tokens int,
         cost_usd numeric(10,6), latency_ms int, model text, trace_id text, created_at)

-- Governance, Usage & Security Auditing
usage_events(id bigserial pk, org_id fk, user_id fk ON DELETE SET NULL, event_type, tokens, cost_usd, created_at)

audit_logs(id uuid pk, org_id fk ON DELETE CASCADE, user_id fk ON DELETE SET NULL,
           action, resource_type, resource_id, ip_address, user_agent, status, details json, created_at)
  INDEX ix_audit_logs_org_created (org_id, created_at)
```

---

# PART 4 — Key Architectural Modules & Reference Behavior

## 4.1 Reciprocal Rank Fusion (`backend/app/services/retrieval.py`)

```python
def reciprocal_rank_fusion(
    ranked_lists: list[list[str]], k: int = 60, top_n: int = 30
) -> list[str]:
    scores: dict[str, float] = {}
    for lst in ranked_lists:
        for rank, doc_id in enumerate(lst, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return sorted_ids[:top_n]
```

## 4.2 Tenant & Session Security (`backend/app/deps.py`, `core/security.py`)

* Every access and refresh token embeds a unique `jti` and `iat_ms`.
* `get_current_user` checks `is_token_jti_revoked` (populated on `POST /api/v1/auth/logout`) and `is_user_token_revoked` (populated immediately upon `delete_member`), matches `token_org_id == str(user.org_id)`, and sets `app.current_org_id` on PostgreSQL sessions.
* All conversation routes (`GET`, `DELETE`, `POST /ask`) enforce both `org_id` AND `user_id == current_user.id`.

## 4.3 Measured Evaluation Results (`EVALUATION.md` & CI Gate)

| Config | Faithfulness | Answer Relevancy | Hit@5 | MRR | Refusal Acc | p95 Latency | Cost / Query |
|---|---|---|---|---|---|---|---|
| **v1 Naive Baseline** | 0.72 | 0.78 | 0.70 | 0.56 | 0.40 | 0.44s | $0.0031 |
| **v2 Hybrid + Multi-Query** | 0.82 | 0.86 | 0.84 | 0.72 | 1.00 | 0.61s | $0.0044 |
| **v3 Full Enterprise Stack** | **0.90** | **0.91** | **0.92** | **0.84** | **1.00** | 0.78s | $0.0048 |

*(Latest CI regression gate run on `eval/run_eval.py --version v3 --ci-gate --min-faithfulness 0.85` achieved **0.943 faithfulness**.)*

---

# PART 5 — Operations, Testing & Google Cloud Deployment

* **Local Development:** `docker compose up -d --build` runs the 8-container stack (PostgreSQL + pgvector, Redis, SeaweedFS S3, FastAPI API, Celery Worker, Prometheus, Grafana, Next.js Frontend).
* **Production / Google Cloud:** [`deploy/gcp/deploy.sh`](deploy/gcp/deploy.sh) prepares an Ubuntu Compute Engine VM (`e2-standard-2` recommended), opens only `22`/`80`/`443` via UFW, generates cryptographic secrets into `.env` (`chmod 600`), provisions Let's Encrypt HTTPS certificates when a domain is supplied, and runs `docker-compose.prod.yml` behind hardened Nginx.
* **Test Verification:** `pytest tests/ -v` runs **34 automated integration and security tests** inside the containerized PostgreSQL + pgvector & Redis environment (`34 passed`).
