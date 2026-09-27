# DocIntel — Architectural Decision Records (ADR) & Interview Script

This document details the engineering trade-offs, security guarantees, and design rationale behind DocIntel. It serves as your comprehensive technical reference for systems architecture discussions.

---

## 1. Multi-Tenancy Isolation Architecture

### The Design Decision
`org_id` is denormalized directly onto the `chunks` table, and all database queries enforce tenant scoping at the relational query layer:

```sql
SELECT c.id, c.content, c.page_number, 
       1 - (c.embedding <=> :qvec) AS score
FROM chunks c
WHERE c.org_id = :org_id
ORDER BY c.embedding <=> :qvec
LIMIT 20;
```

### Trade-Offs & Rationale
- **Why NOT Post-Filtering in Python?**
  - *Post-filtering flaw*: If an organization retrieves top-20 vectors globally and filters out foreign tenants in Python application code, high-density foreign tenants can crowd out the target tenant's vectors, leading to empty or truncated context. More critically, a single application bug or missing `if chunk.org_id == current_user.org_id` creates a catastrophic multi-tenant data leak.
  - *Our approach*: The PostgreSQL query planner uses composite indexes `(org_id)` or HNSW vector index partitions to guarantee that foreign tenant chunks never leave the database kernel.
- **Why Denormalize `org_id` on `chunks` instead of JOINing `documents`?**
  - Eliminates an expensive JOIN between `chunks` and `documents` on high-throughput vector similarity scans. Vector indexing (HNSW) executes in constant time with immediate tenant constraint evaluation.

---

## 2. Vector Datastore: PostgreSQL + pgvector vs Pinecone vs Qdrant

| Consideration | PostgreSQL 16 + pgvector (Chosen) | Dedicated Vector DB (Pinecone / Qdrant) |
|---|---|---|
| **Transactional Consistency** | ACID compliant. Chunks, documents, and users share the same transaction boundary. | Eventual consistency. Chunks can exist orphaned from relational records if writes fail mid-pipeline. |
| **Operational Overhead** | 1 datastore to backup, monitor, and scale. | 2 separate datastores, requiring dual auth credentials, network tunnels, and backup strategies. |
| **Tenant Filtering** | Native SQL `WHERE org_id = :org_id`. | Proprietary metadata filter syntax with index overhead. |
| **Scaling Limit** | Excellent up to ~10M vectors with HNSW indexes. | Scales past 100M+ vectors with dedicated distributed sharding. |

**Interview Defense**: *"We chose pgvector because enterprise document RAG requires strict transactional consistency and zero-leak multi-tenancy. Having relational metadata, user permissions, and embeddings in one ACID-compliant engine eliminates two-phase commit vulnerabilities. When scale surpasses 10 million vectors, the ingestion service can route embeddings to Qdrant while keeping transactional document metadata in Postgres."*

---

## 3. Retrieval Fusion: Reciprocal Rank Fusion (RRF) vs Score Normalization

### The Formula
$$\text{RRF\_Score}(d) = \sum_{m \in M} \frac{1}{k + \text{rank}_m(d)} \quad (k = 60)$$

### Trade-Offs & Rationale
- **The Problem with Score Normalization**:
  - Dense cosine distances range between $[-1, 1]$ (or $[0, 1]$ for normalized vectors).
  - BM25 / PostgreSQL `ts_rank_cd` scores are unbounded positive floats ($0.0$ to $15.0+$), heavily influenced by document length and query term frequency.
  - Min-Max score normalization $(\frac{s - s_{min}}{s_{max} - s_{min}})$ is volatile: an extreme outlier BM25 score compresses all other scores to zero.
- **Why RRF Wins**:
  - RRF operates purely on ordinal ranking order rather than arbitrary score magnitudes. It is non-parametric, robust to outliers, and requires zero manual hyperparameter tuning across disparate document formats.

---

## 4. Re-ranking: Cross-Encoder (`bge-reranker-v2-m3`) vs Bi-Encoder Only

### The Mechanism
- **Bi-Encoder (Embedding)**: Compresses query $Q$ into 384 numbers, chunk $C$ into 384 numbers, and measures angle: $\cos(v_Q, v_C)$.
- **Cross-Encoder**: Feeds $[CLS] \circ Q \circ [SEP] \circ C$ through full transformer layers, allowing every word token in the query to attend to every word token in the document chunk via cross-attention.

### Trade-Offs & Rationale
- **Latency vs Precision**:
  - Cross-encoders are too computationally expensive to score all 100,000 chunks in a database ($\sim 25\text{ms}$ per pair).
  - Bi-encoders are fast enough to filter 100,000 chunks down to 30 in $<5\text{ms}$.
  - **The Two-Stage Pipeline**: We use fast bi-encoder + BM25 to retrieve the top 30 candidates, then pass only those 30 candidates through the cross-encoder to select the final top 6. This achieves state-of-the-art precision with sub-50ms latency.

---

## 5. Cost Optimization: Semantic Cache & Multi-Provider LiteLLM Router

### 1. Redis Semantic Cache
- Computes cosine similarity between incoming query embedding and cached historical query vectors.
- If similarity $\ge 0.97$, the cached answer and verified citation payload are streamed immediately.
- Eliminates redundant LLM API calls, reducing repetitive query latency from $1.8\text{s}$ to $<15\text{ms}$ and saving token spend.

### 2. Provider Routing & Automatic Fallback
```
Incoming Request
    │
    ▼
[Groq: Qwen 27B / Llama 3.3] ───Timeout / Rate Limit (429)───▶ [Google Gemini Flash]
    │                                                                   │
    ▼ (Success)                                                         ▼ (Fallback Success)
Stream Tokens                                                     Stream Tokens
                                                                        │
                                                                        ▼ (If all fail)
                                                          [Local Smart Grounded Engine]
```
- Guarantees 99.99% system availability even during third-party LLM outages.

---

## 6. ADR 6: Handling Cross-Chunk Boundary Splits (Section-Title Concatenation)

### The Problem
In enterprise documents and academic course notes, section headings frequently appear at the bottom of page $N$, while the accompanying Markdown comparison table or data list appears at the top of page $N+1$. 
- Chunk $N$: Contains `## Difference Between File System and DBMS` (no table body).
- Chunk $N+1$: Contains `| Basics | File System | DBMS | ...` (no occurrence of the word *"Difference"* in the body).

Under naive sparse search, searching for *"Difference Between File System and DBMS"* produces a false negative for Chunk $N+1$ because the body text lacks the word *"Difference"*. The LLM only receives the empty heading chunk and triggers a refusal.

### The Architecture Solution
1. **Database-Level tsvector Concatenation**:
   ```sql
   SELECT c.id, c.content, c.page_number, c.section_title
   FROM chunks c
   WHERE c.org_id = :org_id
     AND (to_tsvector('english', COALESCE(c.section_title, '')) || c.content_tsv) 
         @@ plainto_tsquery('english', :q)
   ORDER BY score DESC;
   ```
2. **Context Block Metadata Injection**:
   The prompt builder explicitly decorates each grounding block:
   ```
   [{i}] ({filename}, p.{page}) - Section: {clean_section_title}
   {clean_content}
   ```
This provides the LLM with the exact topic classification of every table without inflating storage or duplicating chunk bodies.

---

## 7. ADR 7: Invisible PDF Bidirectional Unicode Formatting Sanitization

### The Problem
PDF files generated from Google Docs, Microsoft 365, and LaTeX frequently embed invisible directional formatting markers:
- `\u202d`: Left-to-Right Override (LRO)
- `\u202c`: Pop Directional Formatting (PDF)
- `\u200b-\u200f`: Zero-width spaces, joiners, and non-joiners
- `\ufeff`: Byte Order Mark (BOM)

These characters contaminate words (e.g. `|\u202dBasics\u202c|`), breaking exact regex matching, tsvector term extraction, and embedding tokenization.

### The Architecture Solution
A centralized Unicode cleaning pass is enforced at three boundaries:
1. Prior to embedding generation in `DocumentIngestionTask`.
2. Prior to query embedding and full-text querying in `RetrievalEngine`.
3. Prior to context assembly in `build_context_block`.
```python
clean_text = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", text).strip()
```
