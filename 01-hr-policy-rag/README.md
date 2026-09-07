# Project 01 — HR Policy Q&A Bot

Simple, clean RAG pipeline. The foundation all other projects build on.

## What it demonstrates
- `SimpleDirectoryReader` — loads .md, .txt, .pdf from a directory
- `SentenceSplitter` — chunks documents with configurable size and overlap
- `OllamaEmbedding` — local embeddings via nomic-embed-text
- `VectorStoreIndex` — in-memory FAISS-style index (no vector DB infra needed)
- `VectorIndexRetriever` — top-k semantic retrieval
- Custom `PromptTemplate` — domain-specific tone (HR assistant persona)
- Source attribution — every answer cites the policy section and relevance score

## Run

```bash
cd 01-hr-policy-rag
pip install -r requirements.txt

# Interactive CLI
python main.py

# Single question
python main.py --question "How many days of parental leave do I get?"

# Custom docs directory
python main.py --data-dir /path/to/your/hr/docs
```

## Architecture

```
data/hr_policy.md
      │
      ▼ SimpleDirectoryReader
      │
      ▼ SentenceSplitter (chunk_size=512, overlap=64)
      │
      ▼ OllamaEmbedding (nomic-embed-text, 768 dims)
      │
      ▼ VectorStoreIndex (in-memory)
      │
      ▼ VectorIndexRetriever (top_k=4)
      │
      ▼ RetrieverQueryEngine
      │  └─ Custom HR PromptTemplate
      │
      ▼ Groq llama-3.3-70b-versatile
      │
      ▼ Answer + source citations
```

## Sample Questions

- "How many days of annual leave am I entitled to?"
- "Can I carry over unused leave? How many days?"
- "What is the remote work policy — how many days per week?"
- "What are the core working hours when I'm remote?"
- "How do I submit an expense claim and what's the deadline?"
- "What does the parental leave policy say for primary caregivers?"
- "What happens if I'm rated below expectations twice?"
