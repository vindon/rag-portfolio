# Project 02 — Contract Review Assistant

Multi-turn chat with contracts using conversation memory and streaming.

## What it demonstrates (beyond Project 01)
- `CondensePlusContextChatEngine` — rewrites follow-up questions with conversation history
- `ChatMemoryBuffer` — retains the last 4,096 tokens of context across turns
- Streaming token output → `st.write_stream()` in Streamlit
- Multi-file upload — index multiple contracts in one session
- Source cards — every response links back to the specific contract clause

## Run

```bash
cd 02-contract-review-chat
pip install -r requirements.txt
streamlit run app.py
```

## Key Design Decisions

**Why CondensePlusContextChatEngine?**  
A user might ask "Does clause 8 limit liability?" and follow up with "What about for data breaches?"  
CondensePlusContextChatEngine rewrites the follow-up into a standalone question before retrieval:  
"Does clause 8 limit liability for data breaches?" — so the retrieval stays accurate across turns.

**Why ChatMemoryBuffer with 4,096 token limit?**  
Contracts can be long. A 4,096-token buffer retains ~3,000 words of conversation — enough for  
10–15 exchanges without hitting LLM context limits.

## Starter Prompts
- "Summarise the key obligations of each party"
- "What are the payment terms?"
- "Identify any unusual or high-risk clauses"
- "Who owns the IP created under this agreement?"
- "What's the dispute resolution process?"
