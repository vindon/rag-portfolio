# RAG Portfolio — Five Production-Grade Applications

A progression of five real-world RAG applications demonstrating enterprise AI engineering skills,
built with **Groq (primary LLM)**, **Ollama nomic-embed-text (embeddings)**, and a provider-swap
fallback system that works by editing a single `.env` line.

> **Stack:** Groq `llama-3.3-70b-versatile` · Ollama `nomic-embed-text` · Qdrant · Milvus Lite · Weaviate · LangGraph · LlamaIndex · Streamlit

---

## Projects at a Glance

| # | Project | Concepts | Vector DB | Interface |
|---|---------|----------|-----------|-----------|
| 01 | [HR Policy Q&A Bot](#01-hr-policy-qa-bot)         | SimpleDirectoryReader, SentenceSplitter, VectorStoreIndex, source attribution | In-memory | CLI |
| 02 | [Contract Review Assistant](#02-contract-review-assistant) | Multi-doc, ChatMemoryBuffer, CondensePlusContextChatEngine, streaming | In-memory | Streamlit |
| 03 | [Marketing Content Hub](#03-marketing-content-hub) | Qdrant collections, metadata filtering, template routing, content types | Qdrant | Streamlit |
| 04 | [TechDocs RAG Pipeline](#04-techdocs-rag-pipeline) | Milvus Lite, BM25, RRF hybrid search, CrossEncoder reranking, eval | Milvus Lite | Streamlit |
| 05 | [IT Helpdesk Agent](#05-it-helpdesk-agent)         | LangGraph supervisor pattern, Weaviate embedded, DuckDuckGo, SQLite, Google Calendar | Weaviate | Streamlit |

---

## Quick Start

```bash
# Clone
git clone https://github.com/yourusername/rag-portfolio.git
cd rag-portfolio

# One-command setup (macOS ARM64)
chmod +x setup.sh && ./setup.sh

# Add your Groq key (free at https://console.groq.com)
echo "GROQ_API_KEY=your_key_here" >> .env

# Run any project
cd 01-hr-policy-rag && python main.py
cd 02-contract-review-chat && streamlit run app.py
cd 03-marketing-content-hub && streamlit run app.py
cd 04-techDocs-rag-pipeline && streamlit run app.py
cd 05-it-helpdesk-agent && streamlit run app.py
```

---

## Architecture

### Provider Abstraction Layer

All five projects share a `shared/` module that decouples the business logic from the LLM and embedding provider. Switch providers with one line in `.env`:

```bash
LLM_PROVIDER=groq        # or: gemini | ollama
EMBED_PROVIDER=ollama    # or: gemini | huggingface
```

```
┌─────────────────────────────────────────────┐
│                  .env                        │
│  LLM_PROVIDER=groq  EMBED_PROVIDER=ollama   │
└───────────────────┬─────────────────────────┘
                    │
           ┌────────▼────────┐
           │   shared/        │
           │  llm_factory.py  │◄── Projects 01–04 (LlamaIndex LLM)
           │  embedder_factory│◄── All projects (embeddings)
           │  config.py       │
           └─────────────────┘
```

### Vector DB Strategy

| Project | DB | Mode | Why |
|---------|-----|------|-----|
| 01, 02  | LlamaIndex VectorStoreIndex | In-memory | No infra needed; demo-friendly |
| 03      | Qdrant | `:memory:` (or Docker) | Multi-collection per content type |
| 04      | Milvus Lite | `./milvus.db` | Embedded file DB; BM25 hybrid |
| 05      | Weaviate | Embedded process | Native object properties; manual vectors |

---

## 01 HR Policy Q&A Bot

**Use case:** Employees ask plain-English questions about leave, remote work, expense policy.

**Architecture:**
```
hr_policy.md
    │
    ▼ SimpleDirectoryReader
    │
    ▼ SentenceSplitter (512 tokens / 64 overlap)
    │
    ▼ OllamaEmbedding (nomic-embed-text)
    │
    ▼ VectorStoreIndex (in-memory FAISS)
    │
    ▼ VectorIndexRetriever (top-4)
    │
    ▼ RetrieverQueryEngine + HR Prompt Template
    │
    ▼ Groq LLM → Answer + section citation
```

**Run:** `cd 01-hr-policy-rag && python main.py`

---

## 02 Contract Review Assistant

**Use case:** Legal and procurement teams analyse contracts via a multi-turn chat UI.

**New concepts over 01:**
- `CondensePlusContextChatEngine` — rewrites follow-up questions using conversation history
- `ChatMemoryBuffer` — retains the last 4,096 tokens of conversation context
- Streaming token output to Streamlit via `st.write_stream()`
- Multi-file support (upload multiple contracts, all indexed together)

**Run:** `cd 02-contract-review-chat && streamlit run app.py`

---

## 03 Marketing Content Hub

**Use case:** Marketing generates grounded LinkedIn posts, blog articles, demo scripts, email sequences, and case study snippets from a product knowledge base.

**New concepts over 02:**
- **Qdrant collections:** Three separate vector collections (`product_features`, `case_studies`, `faqs`)
- **Template routing:** `ContentType` enum selects system prompt + user template per format
- **Collection targeting:** Each content type searches only relevant collections (e.g. case study snippets search only `case_studies`)

**Run:** `cd 03-marketing-content-hub && streamlit run app.py`

---

## 04 TechDocs RAG Pipeline

**Use case:** Engineering teams query technical API documentation with the highest retrieval precision.

**New concepts over 03:**
- **Milvus Lite** embedded vector store (`./milvus.db`) — no Docker, persistent
- **BM25 sparse retrieval** — keyword matching via `rank-bm25`
- **RRF hybrid fusion** — `QueryFusionRetriever` merges dense + sparse rankings
- **CrossEncoder reranking** — `ms-marco-MiniLM-L-6-v2` re-scores top candidates
- **LLM-as-judge evaluation** — `FaithfulnessEvaluator` + `RelevancyEvaluator`

**Retrieval pipeline:**
```
Query
  ├─► Dense Retriever (Milvus ANN, top-8)   ─┐
  └─► Sparse Retriever (BM25, top-8)         ─┼─► RRF Fusion (top-6)
                                              ─┘        │
                                                        ▼
                                              CrossEncoder Rerank (top-3)
                                                        │
                                                        ▼
                                              Groq LLM Synthesis
```

**Run:** `cd 04-techDocs-rag-pipeline && streamlit run app.py`

---

## 05 IT Helpdesk Agent

**Use case:** Employees submit IT support requests that are automatically routed to the right resolution path — KB search, web search, or ticket creation with optional calendar scheduling.

**New concepts over 04:**
- **LangGraph StateGraph** — explicit graph topology with typed shared state
- **Supervisor pattern** — Groq LLM routes between specialist agents
- **Weaviate Embedded** — vector DB with manual embedding via Ollama
- **DuckDuckGo search** — zero-cost web search for issues not in the KB
- **SQLite ticket tracker** — zero-dependency ticket CRUD
- **Google Calendar** — schedules technician visits (falls back to demo mode)

**Agent graph:**
```
START → Supervisor → RAG Agent → Supervisor → END
                  ↓                         ↑
              Search Agent ─────────────────┘
                  ↓
              Tools Agent (Ticket + Calendar) → END
```

**Run:** `cd 05-it-helpdesk-agent && streamlit run app.py`

---

## Project Structure

```
rag-portfolio/
├── .env.example              # Copy to .env, add GROQ_API_KEY
├── docker-compose.yml        # Optional: Qdrant, Milvus, Weaviate
├── setup.sh                  # macOS ARM64 one-command setup
├── shared/                   # Provider abstraction (all projects import this)
│   ├── config.py
│   ├── llm_factory.py        # get_llm() → LlamaIndex | get_langchain_llm() → LangChain
│   ├── embedder_factory.py   # get_embedder() + get_embedding_fn()
│   └── utils.py
├── 01-hr-policy-rag/
├── 02-contract-review-chat/
├── 03-marketing-content-hub/
├── 04-techDocs-rag-pipeline/
└── 05-it-helpdesk-agent/
```

---

## Fallback Providers

| Scenario | LLM | Embeddings |
|----------|-----|-----------|
| Primary (default) | Groq `llama-3.3-70b-versatile` | Ollama `nomic-embed-text` |
| No Ollama | Groq `llama-3.3-70b-versatile` | Gemini `text-embedding-004` |
| No API keys | Ollama `llama3.2` (local) | Ollama `nomic-embed-text` |
| Fully offline | Ollama `llama3.2` | HuggingFace `BAAI/bge-small-en-v1.5` |

Set `LLM_PROVIDER` and `EMBED_PROVIDER` in `.env`. All five projects pick up the change automatically.

---

## Requirements

- **Python 3.11+**
- **Ollama** (local embedding): `brew install ollama && ollama pull nomic-embed-text`
- **Groq API key** (free): https://console.groq.com
- **macOS ARM64** (M-series): native support confirmed for all packages

---

*Built to demonstrate end-to-end RAG engineering — from document ingestion through hybrid retrieval, reranking, evaluation, and multi-agent orchestration.*
