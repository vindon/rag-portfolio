# Project 03 — Marketing Content Hub

Generate grounded marketing content from a product knowledge base using Qdrant.

## What it demonstrates (beyond Project 02)
- **Qdrant vector collections** — three separate collections per knowledge type
- **Metadata filtering** — retrieval scoped by category at query time
- **Template routing pattern** — one LLM, five content formats, five system prompts
- **ContentType enum** — maps each format to the correct prompt + target collections
- **Multi-collection retrieval** — LinkedIn posts pull from features + case_studies simultaneously

## Run

```bash
cd 03-marketing-content-hub
pip install -r requirements.txt
streamlit run app.py
```

## Content Types

| Format | System Persona | Target Collections | Expected Output |
|--------|---------------|-------------------|-----------------|
| LinkedIn Post | B2B content marketer | features, case_studies | 150–250 words, hook + insight + CTA |
| Blog Article | Content strategist | all three | 800–1,200 words with H2 structure |
| Demo Script | Sales engineer | features, case_studies | 500–800 words with stage directions |
| Email Campaign | Demand gen specialist | case_studies, faqs | 3 emails × 150–200 words |
| Case Study Snippet | Sales writer | case_studies | 80–120 word proof point |

## Qdrant Collections

```
product_features  ← core capabilities, pricing, technical specs
case_studies      ← FashionHub, CloudServe, QuickFreight results
faqs              ← objection handling, sales questions
```

Qdrant runs in `:memory:` mode by default (no Docker needed).  
For persistence, set `QDRANT_URL=http://localhost:6333` in `.env` and run `docker compose up qdrant`.
