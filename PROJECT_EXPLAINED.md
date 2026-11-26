# DocIntel — Platform Explained

Welcome to **DocIntel**, an enterprise-grade, security-hardened multi-tenant document intelligence platform built to ingest organizational documents (PDF, DOCX, XLSX, TXT, MD), index them via layout-aware chunking and hybrid retrieval, and stream grounded answers with verified page-level inline citations.

---

## 1. Core Problem & End-to-End Solution

Enterprise teams store critical records across siloed financial filings, contracts, and policy PDFs where standard search and naive RAG fail:
1. **Broken table & cross-page retrieval**: Naive fixed-size splitting breaks tables and separates section headings from table bodies.
2. **LLM hallucinations & unverified answers**: Unsupported generations invent figures or fabricate sources.
3. **Cross-tenant & same-tenant leaks**: Weak SQL or object checks risk data leakage across companies or between users in private chats.
4. **Security & upload risks**: Unchecked uploads, missing rate limits, and stale JWTs leave multi-tenant SaaS apps vulnerable in production.
5. **Unbounded LLM costs**: Single-provider outages, duplicate queries, and uncapped usage burn API budgets.

**How DocIntel solves these challenges in production:**
* **Zero-Leak Multi-Tenancy + RLS Context**: `org_id` is denormalized on `chunks`, enforced in every SQL `WHERE` clause, verified against JWT claims in `deps.py`, and bound per session via PostgreSQL `set_config('app.current_org_id', ...)`. Same-organization private conversations enforce `Conversation.user_id == current_user.id`.
* **Defense-in-Depth Application & GenAI Security**: Magic-byte + Zip-bomb file upload validation (`documents.py`), directory-traversal guards (`storage.py`), SlowAPI rate limiting + Redis brute-force lockout, JWT `jti` blacklisting & refresh rotation, instant token revocation upon member removal, HTTP security headers, prompt-injection detection, Luhn-checked PII/secret redaction (`guardrails.py`), and an immutable `AuditLog` (`audit_logs`).
* **Asynchronous Celery Ingestion**: Document downloads, multi-format parsing (`PyMuPDF`, `python-docx`, `openpyxl`), Unicode sanitization, `LayoutChunker`, and `BAAI/bge-small-en-v1.5` batched embeddings run asynchronously on Celery workers with exponential backoff retries (`max_retries=3`).
* **Section-Aware Hybrid Retrieval**: Combines dense `pgvector` HNSW cosine search with PostgreSQL sparse full-text search over concatenated `(to_tsvector('english', section_title) || content_tsv)`, merged via Reciprocal Rank Fusion ($k=60$) and re-ranked by `BAAI/bge-reranker-v2-m3`.
* **Verified Citations & Resilient LLM Cascade**: Routes queries through `LiteLLM` (`Groq → Gemini → OpenAI → Local Grounded Engine`) with `<retrieved_context>` prompt isolation and post-check regex citation verification (`verify_and_clean_citations()`).
* **Full-Stack Telemetry & Quality Gates**: Langfuse v4 OpenTelemetry tracing (`SPAN → RETRIEVER → GENERATION` with `session_id`, `user_id`, and tenant tags), Prometheus + Grafana metrics, Ruff lint/formatting, **34 automated pytest tests**, and a CI retrieval quality gate ($\ge 0.85$ faithfulness).

---

## 2. Annotated Project Directory Structure

```text
├── .agents/skills/langfuse/     # Installed Langfuse AI Skill & best-practices guides
├── .github/workflows/ci.yml     # GitHub Actions CI: Ruff, Mypy, Pytest, Docker & Eval Gate
├── backend/
│   ├── alembic/                 # Alembic PostgreSQL + pgvector migrations
│   ├── app/
│   │   ├── api/v1/              # FastAPI REST API Controllers
│   │   │   ├── admin.py         # Tenant usage, budgets, member invite/delete, audit-logs
│   │   │   ├── auth.py          # Register, login, refresh rotation, logout & /me
│   │   │   ├── chat.py          # SSE streaming chat, prompt-injection check & BOLA guard
│   │   │   ├── documents.py     # Magic-byte upload validation, status polling & deletion
│   │   │   ├── health.py        # Liveness & leak-free readiness probes
│   │   │   └── router.py        # API v1 router registry
│   │   ├── core/                # Core infrastructure & security
│   │   │   ├── errors.py        # Domain HTTP exception handlers
│   │   │   ├── logging.py       # JSON structured logging & X-Request-ID correlation
│   │   │   ├── rate_limit.py    # Redis-backed SlowAPI Limiter
│   │   │   ├── security.py      # BCrypt, JWT JTI revocation & login lockout tracking
│   │   │   └── tracing.py       # Langfuse v4 OTel context propagation & spans
│   │   ├── models/              # SQLAlchemy 2.0 Async ORM entities
│   │   │   ├── audit.py         # Immutable AuditLog table (org/user/IP/action/details)
│   │   │   ├── base.py          # Base metadata & UTC TimestampMixin
│   │   │   ├── chat.py          # Conversation and Message models
│   │   │   ├── chunk.py         # Chunk with Vector(384) HNSW & persisted TSVECTOR GIN
│   │   │   ├── document.py      # Document entity, status enum & SHA-256 hash
│   │   │   ├── org.py           # Organization entity & monthly token budget
│   │   │   ├── usage.py         # UsageEvent cost/token ledger
│   │   │   └── user.py          # User accounts, RBAC roles & passive_deletes
│   │   ├── schemas/             # Pydantic v2 validation schemas
│   │   ├── scripts/             # reindex_embeddings.py & seed.py
│   │   ├── services/            # Business, RAG & security logic
│   │   │   ├── audit.py         # AuditService event writer & tenant query helper
│   │   │   ├── auth_service.py  # Auth, privilege escalation guards, lockout & revocation
│   │   │   ├── budget.py        # Atomic quota check & monthly usage increment
│   │   │   ├── cache.py         # Redis semantic cache (org-namespaced, >= 0.97 cosine)
│   │   │   ├── chunking.py      # LayoutChunker (700 tokens, 100 overlap, tables intact)
│   │   │   ├── embeddings.py    # fastembed / SentenceTransformer + SHA-256 fallback
│   │   │   ├── generation.py    # LiteLLM waterfall, PII masking, XML fence & verifier
│   │   │   ├── guardrails.py    # Prompt-injection detection & PII/secret redaction
│   │   │   ├── parsing.py       # PyMuPDF / python-docx / openpyxl layout parser
│   │   │   ├── retrieval.py     # QueryRewriter, pgvector, BM25, RRF & CrossEncoderReranker
│   │   │   └── storage.py       # S3/SeaweedFS client with traversal-safe local fallback
│   │   ├── static/index.html    # Embedded standalone dev UI (disabled in production)
│   │   ├── workers/             # Celery app & process_document_pipeline task
│   │   ├── config.py            # Environment settings with prod fail-fast security check
│   │   ├── deps.py              # AsyncSession, JWT revocation check & Postgres RLS context
│   │   └── main.py              # FastAPI factory, SecurityHeadersMiddleware, CORS & metrics
│   └── tests/                   # 34 automated tests across 7 files
├── frontend/                    # Next.js 15 / React 19 / TypeScript / Tailwind UI
├── eval/                        # 50-question golden benchmark & CI faithfulness gate
├── deploy/gcp/                  # Automated Google Cloud VM deployment script & guide
├── infra/
│   ├── grafana/                 # Metrics dashboards
│   ├── nginx/                   # Hardened reverse proxy & SSL Let's Encrypt template
│   ├── postgres/rls_policies.sql# Optional PostgreSQL Row-Level Security policies
│   └── prometheus/              # Scrape targets
├── ARCHITECTURE.md              # Architecture Decision Records (ADRs)
├── EVALUATION.md                # Evaluation metrics & comparative analysis
├── README.md                    # Main repository guide
├── Project1_Blueprint_DocIntel (1).md # Synced architectural blueprint
├── Project 1 blueprint.docx     # Formatted Microsoft Word blueprint
├── docker-compose.yml           # 8-container local development stack
└── docker-compose.prod.yml      # 7-container hardened production stack
```

---

## 3. End-to-End Execution Lifecycles

### Pipeline 1: Secure Document Ingestion Lifecycle
```text
1. Client POST /api/v1/documents (Multipart File + Bearer JWT)
   ├─► Check file size (>0 and <= 50 MB)
   ├─► Sanitize filename (strip directories / unsafe chars)
   ├─► Verify extension + MIME type + binary magic bytes (%PDF-, PK zip <=100MB, OLE2, text)
   ├─► Compute SHA-256 content hash → return existing doc if already uploaded in same org
   │
2. Stream file to S3 / SeaweedFS (key: org_{org_id}/{doc_id}_{safe_filename})
   │
3. Persist Document (status=QUEUED), write AuditLog (DOCUMENT_UPLOADED), enqueue Celery task
   │
4. Celery Worker (process_document_pipeline)
   ├─► Update status=PARSING → extract PDF tables/blocks, DOCX, or XLSX via DocumentParser
   ├─► Run LayoutChunker (target=700 tokens, overlap=100, preserves tables & section titles)
   ├─► Update status=EMBEDDING → generate batched 384d vectors via EmbeddingService
   ├─► Insert Chunk rows (with denormalized org_id & generated content_tsv)
   └─► Update Document status=READY (or FAILED with error_message; Celery retries up to 3x)
```

### Pipeline 2: Guardrailed Hybrid Retrieval & Re-ranking Lifecycle
```text
1. Client POST /api/v1/chat/conversations/{conversation_id}/ask (SSE + SlowAPI 30/min)
   ├─► Verify prompt-injection guardrails (reject adversarial system overrides -> HTTP 400)
   ├─► Enforce BudgetService monthly token limit (-> HTTP 429 if exceeded)
   ├─► Verify strict conversation ownership (org_id == user.org_id AND user_id == user.id)
   │
2. Semantic Cache Check (Redis hash org:{org_id}:semantic_cache)
   └─► Cosine similarity >= 0.97 → stream cached tokens + citations immediately
   │
3. RetrievalEngine (v3 pipeline inside Langfuse RETRIEVER span)
   ├─► QueryRewriter: coreference resolution + up to 3 query variations
   ├─► Embed queries (384d) and run sequential AsyncSession-safe searches:
   │     • Dense: pgvector HNSW cosine distance (WHERE org_id = :org_id)
   │     • Sparse: Postgres ts_rank_cd over (section_title || content_tsv) (WHERE org_id = :org_id)
   ├─► Reciprocal Rank Fusion (k=60) → top 30 candidate pool
   └─► CrossEncoderReranker (BAAI/bge-reranker-v2-m3 or lexical/table-boost fallback) → top 6
```

### Pipeline 3: Grounded Generation, Privacy & Observability Lifecycle
```text
1. Build Context & Mask PII
   ├─► Strip invisible Unicode artifacts ([\u200b-\u200f\u202a-\u202e\ufeff])
   ├─► Apply redact_pii() (SSNs, private keys, API keys, Luhn cards) before outbound LLM calls
   └─► Wrap chunks inside <retrieved_context>...</retrieved_context> delimiters
   │
2. LiteLLM Provider Cascade
   └─► Groq → Gemini → OpenAI → Local Smart Grounded Extractor (offline safety net)
   │
3. Citation Post-Check (verify_and_clean_citations)
   └─► Strip invalid [n] markers or return clean refusal if no context supports the query
   │
4. Persist Usage & Emit Langfuse v4 Trace
   ├─► Record Message, increment Organization tokens_used_this_month, log UsageEvent
   └─► Flush Langfuse OTel trace (root SPAN, cache SPAN, RETRIEVER, GENERATION) with session_id
```

---

## 4. Security & Governance Matrix

| Control Layer | Mechanism Implemented | Primary File(s) |
|---|---|---|
| **Session & Token Auth** | JWT `jti` blacklist on `/auth/logout`, refresh rotation, instant user revocation on delete | [`security.py`](backend/app/core/security.py), [`deps.py`](backend/app/deps.py) |
| **Brute-Force & Abuse** | SlowAPI tenant/IP limits + Redis 5-attempt login lockout (15 min cooldown) + Nginx limit zone | [`rate_limit.py`](backend/app/core/rate_limit.py), [`auth_service.py`](backend/app/services/auth_service.py) |
| **Tenant & Role RBAC** | `org_id` + `user_id` conversation checks, non-Owner invite guards, PostgreSQL RLS context | [`chat.py`](backend/app/api/v1/chat.py), [`rls_policies.sql`](infra/postgres/rls_policies.sql) |
| **Upload Hardening** | Extension + MIME allowlists, magic bytes, Zip-bomb 100 MB cap, safe S3 keys | [`documents.py`](backend/app/api/v1/documents.py), [`storage.py`](backend/app/services/storage.py) |
| **AI & Prompt Safety** | Injection blocker (`400`), XML `<retrieved_context>` isolation, Luhn/PII redaction | [`guardrails.py`](backend/app/services/guardrails.py), [`generation.py`](backend/app/services/generation.py) |
| **Perimeter & Config** | Security headers, HSTS, hidden prod Swagger & demo creds, fail-fast secret validator | [`main.py`](backend/app/main.py), [`config.py`](backend/app/config.py) |
| **Compliance Logging** | Immutable `audit_logs` table + `GET /api/v1/admin/audit-logs` | [`audit.py`](backend/app/models/audit.py), [`admin.py`](backend/app/api/v1/admin.py) |

---

## 5. Verification & Automated CI/CD Gates

On every push/PR to `main` or `develop`, `.github/workflows/ci.yml` executes:
1. **Ruff Lint & Format Check:** Zero lint or formatting violations across `backend/app` and `backend/tests`.
2. **Pytest Suite (34/34 passing):** Covers auth, tenant isolation, BOLA, file magic-byte rejection, brute-force lockout, token revocation, retrieval, citations, guardrails, and audit logging.
3. **Docker Build Validation:** Verifies both `backend` (Python 3.12 non-root image) and `frontend` (Next.js 15 Node 20 image) build cleanly.
4. **RAG Benchmark Regression Gate:** Enforces faithfulness $\ge 0.85$ (`python eval/run_eval.py --version v3 --ci-gate --min-faithfulness 0.85`).
