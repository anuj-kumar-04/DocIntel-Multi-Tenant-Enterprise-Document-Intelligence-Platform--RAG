# PROJECT 1 BLUEPRINT
# "DocIntel" — Multi-Tenant Enterprise Document Intelligence Platform

**Your flagship project. Build this over 4 weeks. Everything below is in build order.**

Target outcome: a live, Dockerized, authenticated, monitored RAG platform with published evaluation numbers — the kind of project that makes an interviewer say *"walk me through your architecture"* instead of *"so, have you used LangChain?"*

---

# PART 0 — What you are building and why

## 0.1 The product, in one paragraph

An organization signs up. Its team members upload PDFs, DOCX and XLSX files (annual reports, contracts, policy manuals, research). Files are parsed asynchronously in the background. Any team member can then ask natural-language questions and get an answer with **inline citations pointing to the exact document and page**, streamed token-by-token. Users from Org A can never see Org B's documents. Admins see usage and token spend. Everything is traced, evaluated and cost-capped.

## 0.2 Why this specific project gets you hired

| Interviewer question it answers | The feature that answers it |
|---|---|
| "Have you built a real backend?" | FastAPI + Postgres + Alembic + JWT auth + RBAC |
| "How do you handle long-running work?" | Celery workers + Redis queue + job status polling |
| "Can you do more than cosine similarity?" | Hybrid BM25 + dense, cross-encoder re-ranking, query rewriting |
| "How do you know your RAG is any good?" | RAGAS golden dataset, eval gate in CI, before/after numbers |
| "How do you control LLM cost?" | LiteLLM router, semantic cache, per-tenant token budgets |
| "What about security/multi-tenancy?" | Row-level tenant isolation enforced at query layer + tested |
| "Can you deploy and operate it?" | Docker Compose → AWS ECS, health checks, Prometheus/Grafana, structured logs |
| "Do you write tests?" | pytest suite + GitHub Actions on every PR |

**The rule for this whole project: if it isn't measured, it doesn't count.** Record numbers at every stage.

## 0.3 Non-negotiables (the credibility checklist)

- [ ] Runs with a single `docker compose up`
- [ ] README with an architecture diagram
- [ ] ≥ 40 tests, all green in CI
- [ ] Live public URL + 90-second demo video
- [ ] `EVALUATION.md` with a before/after retrieval quality table
- [ ] Meaningful commit history on feature branches with PRs (no single "initial commit")
- [ ] `.env.example`, pinned dependencies, no secrets in git

---

# PART 1 — Architecture

## 1.1 System diagram (recreate this in Excalidraw for your README)

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
        │                    FastAPI  (async)                             │
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
   │ 2. parse (Docling/PyMuPDF)│                       │  tracing   │
   │ 3. chunk (layout-aware)  │                        └────────────┘
   │ 4. embed (batch)         │
   │ 5. upsert to pgvector    │                        ┌────────────┐
   └──────────┬───────────────┘                        │ Prometheus │
              │                                        │ + Grafana  │
              ▼                                        └────────────┘
      ┌───────────────┐
      │  S3 / MinIO   │  raw file storage
      └───────────────┘
```

## 1.2 The RAG query pipeline (the part interviewers dig into)

```
User question + chat history
   │
   ├─▶ [1] Semantic cache lookup (Redis, embedding similarity > 0.97)  ──hit──▶ return cached
   │
   ├─▶ [2] Query rewriting: history-aware → standalone question (cheap/fast model)
   │
   ├─▶ [3] Multi-query expansion: generate 3 paraphrases
   │
   ├─▶ [4] Parallel hybrid retrieval per query, tenant-filtered:
   │         • Dense:  pgvector cosine, top 20
   │         • Sparse: Postgres full-text (ts_rank / BM25), top 20
   │         └─ fuse with Reciprocal Rank Fusion → top 30 unique chunks
   │
   ├─▶ [5] Cross-encoder re-rank (bge-reranker-v2-m3) → top 6
   │
   ├─▶ [6] Context assembly: dedupe, token-budget trim, attach [doc_id, page] tags
   │
   ├─▶ [7] Generate: strict prompt — answer ONLY from context, cite every claim
   │         as [1],[2]; if unsupported, say "not found in the documents"
   │
   ├─▶ [8] Post-check: verify every citation index exists; strip hallucinated cites
   │
   └─▶ [9] Stream to client (SSE) + log trace, tokens, cost, latency to Langfuse
```

**Design decisions you must be able to defend in an interview:**
- **Why pgvector over Pinecone?** One datastore for relational + vector = transactional consistency, tenant filtering in the same query, no extra cost/vendor. Trade-off: scales worse past ~10M vectors, where you'd move to Qdrant.
- **Why RRF over score normalization?** Dense and sparse scores aren't on comparable scales; RRF only needs rank order, so it's robust and parameter-light.
- **Why re-rank at all?** Bi-encoder embeddings are compressed and lossy; a cross-encoder reads query+chunk jointly and is far more precise. Cost is limited by only re-ranking 30 candidates.
- **Why multi-query?** Users under-specify. Paraphrases recover recall the single embedding misses.

## 1.3 Tech stack (final, with reasons)

| Layer | Choice | Why this one |
|---|---|---|
| API | **FastAPI** + Pydantic v2, async | Industry default for Python AI backends; native async + OpenAPI docs |
| DB | **PostgreSQL 16 + pgvector** | Relational + vector in one place; tenant filter in the same WHERE |
| ORM/Migrations | SQLAlchemy 2.0 (async) + **Alembic** | Migrations are the signal that you've done real work |
| Queue | **Celery + Redis** | Parsing takes minutes; must not block the request |
| Storage | **MinIO** locally, **S3** in prod | Same S3 API both places |
| Parsing | **Docling** (primary), PyMuPDF fallback, python-docx, openpyxl | Docling handles tables/layout far better than naive text extraction |
| Embeddings | `BAAI/bge-small-en-v1.5` local, or OpenAI `text-embedding-3-small` | bge-small is free, fast, 384-dim, strong on MTEB |
| Re-ranker | `BAAI/bge-reranker-v2-m3` | Best open cross-encoder for the size |
| LLM gateway | **LiteLLM** → Groq (Llama 3.3 70B) primary, Gemini Flash fallback | One interface, automatic fallback, cost tracking built in |
| Orchestration | **LangChain LCEL** for chains (keep LangGraph for Project 2) | Fine here; the pipeline is a DAG, not a state machine |
| Tracing | **Langfuse** (self-hosted in compose) | Free, open-source, shows traces/cost/latency per request |
| Eval | **RAGAS** + a hand-built golden set | Faithfulness, answer relevancy, context precision/recall |
| Frontend | **Next.js 15** + TypeScript + Tailwind + shadcn/ui | Proves you're not Streamlit-only |
| Auth | JWT access+refresh, `passlib[bcrypt]` | Standard; RBAC on top |
| Metrics | prometheus-fastapi-instrumentator + Grafana | Dashboards screenshot beautifully in a README |
| Tests | pytest, pytest-asyncio, httpx, testcontainers | Real Postgres in tests, not mocks |
| CI | GitHub Actions: ruff, mypy, pytest, docker build, eval gate | The team-readiness signal |
| Deploy | Docker Compose → AWS ECS Fargate (or Render to start) | Ship it; a dead demo link is worse than none |

---

# PART 2 — Repository structure

```
docintel/
├── README.md                     # architecture, setup, demo GIF, results
├── EVALUATION.md                 # golden set + before/after metrics tables
├── ARCHITECTURE.md               # decisions + trade-offs (your interview script)
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── .github/workflows/ci.yml
├── Makefile                      # make up / test / eval / migrate / seed
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py               # app factory, middleware, routers, lifespan
│   │   ├── config.py             # pydantic-settings
│   │   ├── deps.py               # get_db, get_current_user, require_role
│   │   ├── api/v1/
│   │   │   ├── auth.py           # register, login, refresh, me
│   │   │   ├── documents.py      # upload, list, status, delete
│   │   │   ├── chat.py           # conversations, ask (SSE stream)
│   │   │   ├── admin.py          # usage, budgets, members
│   │   │   └── health.py         # /health, /ready
│   │   ├── models/               # SQLAlchemy: org, user, document, chunk, conversation, message, usage
│   │   ├── schemas/              # Pydantic request/response
│   │   ├── services/
│   │   │   ├── auth_service.py
│   │   │   ├── storage.py        # S3/MinIO
│   │   │   ├── parsing.py        # Docling + fallbacks
│   │   │   ├── chunking.py       # layout/semantic chunking
│   │   │   ├── embeddings.py     # batched, cached
│   │   │   ├── retrieval.py      # dense + sparse + RRF + rerank
│   │   │   ├── generation.py     # prompt, LLM call, citation post-check
│   │   │   ├── cache.py          # Redis semantic cache
│   │   │   └── budget.py         # per-tenant token accounting
│   │   ├── workers/
│   │   │   ├── celery_app.py
│   │   │   └── tasks.py          # ingest_document pipeline
│   │   └── core/                 # logging, security, errors, rate_limit, tracing
│   └── tests/
│       ├── conftest.py           # testcontainers Postgres+Redis
│       ├── test_auth.py
│       ├── test_tenant_isolation.py   # ← the test that impresses people
│       ├── test_ingestion.py
│       ├── test_retrieval.py
│       ├── test_chat.py
│       └── test_citations.py
│
├── eval/
│   ├── golden_set.jsonl          # 50 Q/A pairs with expected source pages
│   ├── run_eval.py               # RAGAS runner → results/*.json + markdown
│   └── configs/                  # v1_naive.yaml, v2_hybrid.yaml, v3_rerank.yaml
│
├── frontend/
│   ├── Dockerfile
│   ├── app/(auth)/login, (app)/chat, (app)/documents, (app)/admin
│   ├── components/ChatStream.tsx, CitationCard.tsx, UploadDropzone.tsx
│   └── lib/api.ts, useSSE.ts
│
└── infra/
    ├── nginx/nginx.conf
    ├── grafana/dashboards/
    ├── prometheus/prometheus.yml
    └── terraform/               # optional, Phase 8: ECS, RDS, S3, ElastiCache
```

---

# PART 3 — Data model

```sql
-- Tenancy
organizations(id uuid pk, name, slug unique, plan, monthly_token_budget bigint,
              tokens_used_this_month bigint default 0, created_at)

users(id uuid pk, org_id fk→organizations, email unique, hashed_password,
      full_name, role enum('owner','admin','member') default 'member',
      is_active bool, created_at, last_login_at)

-- Documents
documents(id uuid pk, org_id fk, uploaded_by fk→users, filename, s3_key,
          mime_type, size_bytes, page_count,
          status enum('queued','parsing','embedding','ready','failed'),
          error_message text null, chunk_count int default 0,
          created_at, processed_at)
  index (org_id, status)

chunks(id uuid pk, document_id fk→documents, org_id fk,     -- org_id denormalized for fast filtering
       content text, content_tsv tsvector,                   -- generated column for BM25
       embedding vector(384),
       page_number int, chunk_index int,
       section_title text null, element_type text,            -- paragraph|table|list|heading
       token_count int, created_at)
  index (org_id)
  index USING hnsw (embedding vector_cosine_ops)
  index USING gin (content_tsv)

-- Chat
conversations(id uuid pk, org_id fk, user_id fk, title, created_at, updated_at)

messages(id uuid pk, conversation_id fk, role enum('user','assistant'),
         content text, citations jsonb,      -- [{chunk_id, document_id, filename, page, snippet}]
         prompt_tokens int, completion_tokens int, cost_usd numeric(10,6),
         latency_ms int, model text, trace_id text, created_at)

-- Ops
usage_events(id bigserial pk, org_id fk, user_id fk, event_type, tokens, cost_usd, created_at)
  index (org_id, created_at)
```

**Critical multi-tenancy rule:** `org_id` lives on `chunks` (denormalized) so the vector search filters tenant in the *same* SQL statement — no post-filtering, no leak window. Every repository function takes `org_id` as a required first argument. Enforce it in code review of yourself, and pin it with `test_tenant_isolation.py`.

The retrieval SQL, roughly:

```sql
-- dense
SELECT id, content, page_number, document_id,
       1 - (embedding <=> :qvec) AS score
FROM chunks
WHERE org_id = :org_id
ORDER BY embedding <=> :qvec
LIMIT 20;

-- sparse
SELECT id, content, page_number, document_id,
       ts_rank_cd(content_tsv, websearch_to_tsquery('english', :q)) AS score
FROM chunks
WHERE org_id = :org_id
  AND content_tsv @@ websearch_to_tsquery('english', :q)
ORDER BY score DESC
LIMIT 20;
```

Then fuse in Python: `RRF_score(d) = Σ over lists 1/(60 + rank(d))`.

---

# PART 4 — Build plan, phase by phase

Each phase = one feature branch, one PR, tests green before merge. Ship something runnable every phase.

## Phase 1 (Days 1–2) — Skeleton and infrastructure

**Goal:** `docker compose up` gives you a working API and DB.

1. `git init`, repo on GitHub, branch protection on `main` (requires PR + CI green).
2. `docker-compose.yml` with services: `api`, `db` (pgvector/pgvector:pg16), `redis`, `minio`, `worker`.
3. FastAPI app factory, `pydantic-settings` config from env, `/health` and `/ready`.
4. SQLAlchemy async engine, Alembic initialized, first migration creating `organizations` + `users`.
5. Structured JSON logging with a request-id middleware; `ruff` + `mypy` configured.
6. `Makefile`: `up`, `down`, `logs`, `migrate`, `revision`, `test`, `lint`, `seed`, `eval`.
7. GitHub Actions: install → ruff → mypy → pytest → docker build.

**Done when:** CI is green, `curl localhost:8000/health` returns 200 from inside compose.

## Phase 2 (Days 3–4) — Auth, orgs and RBAC

1. `POST /auth/register` — creates an organization + owner user in one transaction.
2. `POST /auth/login` — returns access (15 min) + refresh (7 day) JWTs; bcrypt hashing.
3. `POST /auth/refresh`, `GET /auth/me`.
4. `POST /admin/members` — owner/admin invites a member into their org.
5. `get_current_user` dependency decodes JWT → loads user → attaches `org_id` to request state.
6. `require_role("admin")` dependency for gated routes.
7. Rate limiting (slowapi or a small Redis token bucket): e.g. 60 req/min per user, 10 uploads/hour.

**Tests:** registration, bad password, expired token, refresh flow, member cannot hit admin routes.

## Phase 3 (Days 5–8) — Ingestion pipeline (the heaviest phase)

1. `POST /documents` — multipart upload → validate type + size (cap 50 MB) → stream to S3/MinIO → insert row `status='queued'` → enqueue Celery task → return `202` with `document_id`.
2. `GET /documents` (tenant-scoped list with status) and `GET /documents/{id}/status` for polling.
3. Celery task `ingest_document(document_id)`:
   - `parsing` → Docling extracts text, tables (as markdown), headings, page numbers. Fallback to PyMuPDF on failure; `python-docx` / `openpyxl` by mime type.
   - **Chunking:** keep tables whole; otherwise recursive split at ~700 tokens with 100 overlap, respecting heading boundaries; carry `section_title` and `page_number` into every chunk's metadata.
   - `embedding` → batch of 64 through bge-small; store vectors.
   - Bulk-insert chunks; set `status='ready'`, `chunk_count`, `processed_at`.
   - On exception: `status='failed'` + `error_message`; Celery retry with exponential backoff, max 3.
4. `DELETE /documents/{id}` — remove chunks, S3 object, row (tenant-checked).
5. Idempotency: hash file contents; re-upload of an identical file in the same org returns the existing document.

**Tests:** upload → poll until ready → chunk count > 0 and every chunk has a page number; corrupt PDF ends `failed` with a message; a member of Org B gets 404 for Org A's document.

**Measure now:** ingestion seconds per page, chunks per document. Put it in the README.

## Phase 4 (Days 9–12) — Retrieval and generation

Build in three explicit versions and **keep all three behind a config flag** — this is what lets you show a before/after table.

- **v1 naive:** dense-only top-5 → stuff into prompt. *(Get your baseline number. Do not skip this.)*
- **v2 hybrid:** + BM25, RRF fusion, multi-query expansion.
- **v3 full:** + cross-encoder re-ranking, query rewriting from chat history, citation post-check.

Then:
1. `POST /conversations`, `GET /conversations`, `GET /conversations/{id}/messages`.
2. `POST /conversations/{id}/ask` → **SSE stream**: emits `token` events, then a final `citations` event, then `done`.
3. Generation prompt — strict:
   ```
   Answer using ONLY the numbered context below.
   Cite every factual claim with the bracketed source number, e.g. [2].
   If the context does not contain the answer, reply exactly:
   "I could not find this in the provided documents."
   Never use outside knowledge. Never invent numbers.

   Context:
   [1] (report.pdf, p.14) ...
   [2] (report.pdf, p.15) ...
   ```
4. Citation post-check: regex the emitted `[n]`, drop any index not in context, map survivors to `{document_id, filename, page, snippet}` and persist on the message.
5. Semantic cache: embed the standalone question; if cosine > 0.97 against a cached entry for that org, return the stored answer. Track hit rate.
6. Persist per-message tokens, cost, latency, model, trace_id.

**Tests:** answer to an out-of-corpus question is the refusal string; every returned citation resolves to a real chunk in the same org; hybrid beats naive on a fixed 5-question smoke set.

## Phase 5 (Days 13–14) — Cost control and observability

1. **LiteLLM router:** Groq Llama 3.3 70B primary → Gemini 2.0 Flash fallback → retry with jitter; timeouts everywhere.
2. **Budgets:** before each generation, check `tokens_used_this_month < monthly_token_budget`; over budget → `429` with a clear message. Increment atomically after the call. Reset monthly via Celery Beat.
3. **Langfuse:** wrap the pipeline so each request produces one trace with spans for rewrite / retrieve / rerank / generate, tagged with org and user.
4. **Prometheus:** request count/latency histograms, plus custom gauges — cache hit rate, retrieval latency, tokens per request, ingestion queue depth. Grafana dashboard, screenshot it.
5. `GET /admin/usage` — per-org tokens, cost, top users, docs processed.

## Phase 6 (Days 15–17) — Evaluation (your differentiator)

1. Pick a public corpus: 5–10 annual reports (e.g. Infosys, TCS, Reliance investor PDFs) — public, chart-heavy, realistic.
2. **Hand-write `golden_set.jsonl`: 50 questions.** Mix: 20 factual single-hop, 15 multi-hop/cross-document, 10 table/numeric, 5 unanswerable (must be refused). Each entry: `{question, ground_truth, expected_pages, type}`.
3. `eval/run_eval.py`: runs the golden set against a config (v1/v2/v3), computes
   - **RAGAS:** faithfulness, answer_relevancy, context_precision, context_recall
   - **Retrieval:** Hit@5, MRR, nDCG@5 against `expected_pages`
   - **Refusal accuracy** on the 5 unanswerable questions
   - **Ops:** p50/p95 latency, mean tokens, cost per query
4. Write `EVALUATION.md` with the comparison table and 3–4 sentences of analysis per jump (what improved, what regressed, why).
5. **CI eval gate:** on PRs touching retrieval, run a 15-question subset and fail if faithfulness drops more than 3% from the stored baseline.

Your table will look something like:

| Config | Faithfulness | Ans. Relevancy | Ctx Precision | Hit@5 | MRR | p95 latency | $/query |
|---|---|---|---|---|---|---|---|
| v1 dense-only | 0.71 | 0.78 | 0.52 | 0.68 | 0.54 | 2.1 s | 0.0031 |
| v2 + hybrid + multi-query | 0.81 | 0.85 | 0.69 | 0.83 | 0.71 | 2.8 s | 0.0044 |
| v3 + rerank + rewrite | **0.89** | **0.90** | **0.84** | **0.91** | **0.82** | 3.3 s | 0.0048 |

*(Use YOUR real measured numbers. Never invent them — that's the exact mistake we removed from your resume.)*

## Phase 7 (Days 18–22) — Frontend

1. Next.js 15 App Router, TypeScript, Tailwind, shadcn/ui. Auth pages storing tokens in httpOnly cookies via a route handler.
2. **Documents page:** drag-drop upload, live status badges (poll every 2 s), page/chunk counts, delete.
3. **Chat page:** conversation sidebar, streaming assistant messages, and **clickable citation chips** `[1]` that open a side panel with the source snippet, filename and page. This is the demo moment — make it feel good.
4. **Admin page:** token usage chart, member management, budget display.
5. Loading skeletons, error toasts, empty states, mobile-usable. Polish matters; recruiters judge with their eyes.

## Phase 8 (Days 23–26) — Deploy, harden, document

1. Multi-stage Dockerfiles, non-root user, `.dockerignore`, healthchecks in compose.
2. `docker-compose.prod.yml` + Nginx TLS (Let's Encrypt). Deploy: **Render/Railway** for speed, or **AWS ECS Fargate + RDS Postgres + ElastiCache + S3** for the stronger resume line. Optional Terraform in `infra/terraform`.
3. Security pass: no secrets in git, `gitleaks` in CI, CORS locked to your domain, file-type sniffing (not just extension), size caps, SQL via parameterized queries only, dependency audit (`pip-audit`).
4. Seed script that loads the demo corpus so a visitor sees a working app instantly, plus a read-only demo login on the README.
5. **README:** one-line pitch → demo GIF + live URL + demo creds → architecture diagram → feature list → results table → local setup → API docs link → what I'd do next.
6. **ARCHITECTURE.md:** every decision with its trade-off (your interview prep, written down).
7. 90-second Loom: upload a report → ask a cross-document question → click a citation → show the Langfuse trace and Grafana dashboard.

---

# PART 5 — Reference implementations for the tricky parts

## 5.1 RRF fusion

```python
def reciprocal_rank_fusion(
    ranked_lists: list[list[str]], k: int = 60, top_n: int = 30
) -> list[str]:
    """Fuse ranked ID lists. Rank-based, so incomparable score scales don't matter."""
    scores: dict[str, float] = {}
    for lst in ranked_lists:
        for rank, doc_id in enumerate(lst, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)[:top_n]
```

## 5.2 Retrieval orchestration

```python
async def retrieve(
    self, question: str, org_id: UUID, history: list[Message], cfg: RetrievalConfig
) -> list[Chunk]:
    standalone = await self.rewriter.to_standalone(question, history) if cfg.rewrite else question
    queries = [standalone]
    if cfg.multi_query:
        queries += await self.rewriter.paraphrase(standalone, n=2)

    dense_task  = asyncio.gather(*[self.repo.dense_search(q, org_id, 20) for q in queries])
    sparse_task = asyncio.gather(*[self.repo.sparse_search(q, org_id, 20) for q in queries])
    dense, sparse = await asyncio.gather(dense_task, sparse_task)

    lists = [[c.id for c in r] for r in (*dense, *sparse)] if cfg.hybrid \
            else [[c.id for c in r] for r in dense]
    fused_ids = reciprocal_rank_fusion(lists, top_n=cfg.fusion_top_n)
    candidates = await self.repo.get_chunks(fused_ids, org_id)   # org_id ALWAYS passed

    if cfg.rerank:
        candidates = await self.reranker.rank(standalone, candidates, top_k=cfg.final_k)
    return candidates[: cfg.final_k]
```

## 5.3 The tenant-isolation test (write this early; it's your best "I think about security" artifact)

```python
async def test_org_b_cannot_retrieve_org_a_chunks(client, seed_two_orgs):
    a, b = seed_two_orgs                     # Org A uploaded a doc containing "Zephyrite quarterly margin"
    r = await client.post(
        f"/api/v1/conversations/{b.conversation_id}/ask",
        json={"question": "What is the Zephyrite quarterly margin?"},
        headers=b.auth_headers,
    )
    assert r.status_code == 200
    body = r.text
    assert "could not find this in the provided documents" in body.lower()
    assert body_citations(r) == []
```

## 5.4 Streaming endpoint shape

```python
@router.post("/{conversation_id}/ask")
async def ask(conversation_id: UUID, req: AskRequest,
              user: User = Depends(get_current_user), svc: RagService = Depends()):
    await svc.budget.assert_within_limit(user.org_id)       # 429 if over

    async def events():
        try:
            async for ev in svc.answer_stream(conversation_id, req.question, user):
                yield f"event: {ev.type}\ndata: {ev.json()}\n\n"
        except Exception as e:
            logger.exception("stream_failed", extra={"conv": str(conversation_id)})
            yield f'event: error\ndata: {{"message":"{escape(str(e))}"}}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

---

# PART 6 — Common ways people wreck this project

1. **Skipping the v1 baseline.** Without it you have no before/after table, and the whole eval story collapses. Measure the naive version first, even though it's tempting to jump ahead.
2. **Leaving Docker until the end.** Containerize in Phase 1. Retrofitting is misery.
3. **Building the frontend first.** Backend + eval is what gets you hired; the UI is the wrapper. It comes at Phase 7 for a reason.
4. **Golden set generated by an LLM.** Write the 50 questions by hand from documents you've actually read. LLM-generated ground truth is circular and interviewers ask how you built it.
5. **Post-filtering tenants in Python.** Filter in SQL. A leak found in your own demo is fatal.
6. **One giant commit at the end.** Commit history *is* evidence of process. Branch, PR, merge.
7. **Chunking without page numbers.** If you can't cite a page, the flagship feature dies. Carry metadata from the very first parse.
8. **Free-tier deployment that sleeps.** A recruiter clicking a dead link is worse than no link. Add a keep-alive ping or pay the $7/month.
9. **Claiming numbers you didn't measure.** We removed invented metrics from your resume — don't reintroduce them here.
10. **Scope creep** (voice input! 20 file types! agents!). Ship these 8 phases, deploy, *then* extend.

---

# PART 7 — What this earns on your resume

Replace your current project #1 block with something like this — **filled in with your real measured numbers**:

> **DocIntel — Multi-Tenant Document Intelligence Platform** · [Live Demo] · [GitHub]
> *FastAPI · PostgreSQL/pgvector · Celery · Redis · Next.js · Docker · AWS ECS · Langfuse · RAGAS*
> - Built a multi-tenant RAG platform serving cited, page-level answers over **N documents / M chunks**, with JWT auth, role-based access and SQL-level tenant isolation verified by an automated isolation test suite.
> - Raised answer faithfulness **0.71 → 0.89** and Hit@5 **0.68 → 0.91** (RAGAS, 50-question hand-built golden set) by layering hybrid BM25+dense retrieval with reciprocal rank fusion, multi-query expansion and cross-encoder re-ranking over a dense-only baseline.
> - Engineered asynchronous ingestion with Celery workers (layout-aware parsing, table-preserving chunking, batched embeddings) processing **X pages/sec** with retry and failure surfacing.
> - Cut LLM spend **~40%** via a Redis semantic cache (**Y%** hit rate) and a LiteLLM multi-provider router with automatic fallback and per-tenant token budgets.
> - Shipped with 40+ pytest tests, GitHub Actions CI including a RAGAS regression gate, Prometheus/Grafana dashboards and Langfuse request tracing.

Every one of those lines invites a question you can answer for ten minutes. That is what a strong project does.

---

# PART 8 — Learn-as-you-build resources

- **pgvector:** official README + "pgvector HNSW indexing" docs — read before Phase 4.
- **FastAPI:** the official Advanced User Guide (dependencies, background tasks, SSE).
- **Celery:** "First Steps with Celery" + retry/backoff patterns.
- **Docling:** IBM's GitHub README and examples for table extraction.
- **Hybrid search & RRF:** the original RRF paper (Cormack et al.) — one page, cite it in ARCHITECTURE.md.
- **Re-ranking:** BAAI/bge-reranker model card on Hugging Face.
- **RAGAS:** official docs on metrics definitions — understand what faithfulness actually measures before you quote it.
- **Langfuse:** self-hosting via Docker Compose guide.
- **Alembic:** async migrations tutorial.
- **testcontainers-python:** Postgres fixture pattern for real-DB tests.

---

# Daily rhythm that gets this finished

- 3–4 focused hours on the current phase; end each day with something committed and CI green.
- Log a one-line dev diary per day (`DEVLOG.md`) — problem hit, how you solved it. It becomes your interview story bank and your LinkedIn content.
- One LinkedIn post per phase: screenshot + the specific problem you solved + the number it moved. Eight posts across this build is real visibility.

Build it in order, measure everything, deploy it live. This one project fixes the backend gap, the engineering-discipline gap, the evaluation gap and the "keywords without evidence" gap all at once. Go ship it.
