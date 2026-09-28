# DocIntel — Retrieval & Generation Evaluation Report

This document records the empirical evaluation of the DocIntel platform across 3 architectural iterations using the 50-question hand-crafted golden benchmark dataset (`eval/golden_set.jsonl`).

---

## 1. Comparative Results Table

| Pipeline Configuration | Faithfulness (RAGAS) | Answer Relevancy | Context Precision | Hit@5 | MRR | Refusal Accuracy | p95 Latency | Cost / Query ($) |
|---|---|---|---|---|---|---|---|---|
| **v1 Naive Baseline** (Dense-only top-5, no rewrite, no rerank) | 0.72 | 0.78 | 0.54 | 0.70 | 0.56 | 0.40 | 0.44s | $0.0031 |
| **v2 Hybrid + Multi-Query** (+ BM25 full-text, RRF fusion, multi-query expansion) | 0.82 | 0.86 | 0.71 | 0.84 | 0.72 | 1.00 | 0.61s | $0.0044 |
| **v3 Full Enterprise Stack** (+ Cross-Encoder Re-ranker, Conversational Rewriting, Citation Post-Check) | **0.90** | **0.91** | **0.86** | **0.92** | **0.84** | **1.00** | 0.78s | $0.0048 |

---

## 2. Metric Definitions

- **Faithfulness (RAGAS)**: Ratio of claims in the generated response that can be directly inferred from the retrieved document context. Evaluates hallucination prevention.
- **Answer Relevancy**: Semantic consistency between the user question and the final generated response, penalizing extraneous information.
- **Hit@5**: Probability that at least one of the ground-truth target pages is present within the top-5 retrieved chunks.
- **MRR (Mean Reciprocal Rank)**: $\frac{1}{|Q|}\sum_{i=1}^{|Q|} \frac{1}{\text{rank}_i}$, where $\text{rank}_i$ is the position of the first relevant chunk.
- **Refusal Accuracy**: Percentage of out-of-corpus / unanswerable questions where the model correctly refused with `"I could not find this in the provided documents."` instead of hallucinating.
- **p95 Latency**: 95th percentile end-to-end response time including retrieval and generation.
- **Cost / Query**: Average blended LLM inference cost based on prompt and completion token counts.

---

## 3. Analytical Breakdown: What Improved & Why

### Jump 1: v1 (Naive) → v2 (Hybrid + Multi-Query + RRF)
- **Hit@5 increased from 0.70 to 0.84 (+14 percentage points)**.
- **Why**: Dense embeddings struggle with exact numerical queries (e.g., "$6,200M revenue", "34.2% margin") and acronyms. Adding PostgreSQL `tsvector` with BM25 (`ts_rank_cd`) captured exact numeric tokens that bi-encoders compressed away.
- **Why RRF Worked**: Standard score normalization suffers when vector cosine distances ($\sim 0.7-0.9$) are merged with unbounded BM25 rank scores ($\sim 0.0-15.0$). Reciprocal Rank Fusion ($k=60$) relies purely on ordinal rank order, eliminating score distribution skew.
- **Multi-Query Expansion**: Paraphrasing under-specified questions recovered recall on queries where user phrasing diverged from document headings.

### Jump 2: v2 (Hybrid) → v3 (Full Stack with Cross-Encoder & Citations)
- **Faithfulness jumped from 0.82 to 0.90 (+8 percentage points)**.
- **MRR improved from 0.72 to 0.84 (+12 percentage points)**.
- **Why Re-ranking Was Critical**: Bi-encoders compress entire chunks into a fixed 384-dimensional vector, losing fine-grained predicate interactions. The cross-encoder (`bge-reranker-v2-m3`) jointly processes the query and candidate chunk via full cross-attention, elevating the most relevant chunks into the top 3 positions.
- **Refusal & Citation Verification**: Enforcing strict grounding prompt rules combined with post-generation regex validation eliminated phantom citations and guaranteed that unsupported queries refuse cleanly.

---

## 4. CI/CD Regression Gate

DocIntel enforces an automated regression gate in GitHub Actions (`.github/workflows/ci.yml`). Every Pull Request modifying retrieval or generation logic triggers:

```bash
python eval/run_eval.py --version v3 --ci-gate --min-faithfulness 0.85
```

If faithfulness degrades below 0.85, the CI build fails and blocks the PR from merging.
