# Project 04 — TechDocs RAG Pipeline

Production-grade hybrid retrieval with reranking and evaluation.

## What it demonstrates (beyond Project 03)
- **Milvus Lite** — embedded vector DB (`./milvus.db`), no Docker required on ARM64
- **BM25 sparse retrieval** — keyword matching catches what semantic search misses
- **RRF fusion** — `QueryFusionRetriever` merges dense + sparse with Reciprocal Rank Fusion
- **CrossEncoder reranking** — `ms-marco-MiniLM-L-6-v2` re-scores fused candidates
- **LLM-as-judge eval** — `FaithfulnessEvaluator` + `RelevancyEvaluator` from LlamaIndex
- **Batch eval tab** — downloadable JSON report with per-question scores

## Run

```bash
cd 04-techDocs-rag-pipeline
pip install -r requirements.txt
streamlit run app.py
```

## Retrieval Pipeline

```
Query ──────────────────────────────────────────────────┐
  │                                                       │
  ▼                                                       ▼
Dense Retriever                              BM25 Retriever
(Milvus cosine, top-8)                 (keyword rank, top-8)
  │                                                       │
  └───────────────────► RRF Fusion ◄─────────────────────┘
                        (top-6 merged)
                              │
                              ▼
                    CrossEncoder Reranker
                  (ms-marco-MiniLM, top-3)
                              │
                              ▼
                    Groq LLM Synthesis
```

## Evaluation Metrics

| Metric | What it measures | Score range |
|--------|-----------------|-------------|
| Faithfulness | Is every claim in the answer supported by retrieved context? | 0–1 |
| Relevancy | Does the answer address the question asked? | 0–1 |
| Overall Pass | Passes both thresholds (default: ≥0.5 each) | Pass/Fail |

The evaluator uses Groq as the judge LLM — same model, different prompt.

## Notes on ARM64

`milvus-lite` supports macOS Apple Silicon as of pymilvus 2.4.  
The CrossEncoder model (`ms-marco-MiniLM-L-6-v2`, ~85MB) downloads automatically on first use.
