# Project 05 — IT Helpdesk Multi-Agent System

LangGraph supervisor pattern with four specialist agents, Weaviate embedded KB, and real tools.

## What it demonstrates (beyond Project 04)
- **LangGraph StateGraph** — typed shared state, explicit graph topology
- **Supervisor routing pattern** — Groq LLM with structured output decides next agent
- **Weaviate v4 embedded** — vector store started as a subprocess (no Docker needed)
- **DuckDuckGo search** — free web search when KB has no answer
- **SQLite ticket tracker** — zero-dependency CRUD, generates INC-XXXXXX IDs
- **Google Calendar** — schedules technician visits with real OAuth2 (mock mode without creds)
- **Graceful fallbacks** — every tool has a fallback path so the app never crashes

## Run

```bash
cd 05-it-helpdesk-agent
pip install -r requirements.txt
streamlit run app.py
```

## Agent Graph

```
START
  │
  ▼
Supervisor (Groq structured output → RoutingDecision)
  │
  ├──► RAG Agent (Weaviate KB search + Groq synthesis)
  │         │
  │         └──► Supervisor (reassess)
  │
  ├──► Search Agent (DuckDuckGo + Groq synthesis)
  │         │
  │         └──► Supervisor (reassess)
  │
  └──► Tools Agent (SQLite ticket + Google Calendar)
            │
            └──► END
```

## Tool Stack

| Tool | Technology | Purpose |
|------|-----------|---------|
| Knowledge Base | Weaviate Embedded + Ollama | Search IT documentation |
| Web Search | DuckDuckGo (free) | Find solutions not in KB |
| Ticket Tracker | SQLite | Create/track support tickets |
| Calendar | Google Calendar API | Schedule technician visits |

## Google Calendar Setup (optional)

Without setup, the app runs in demo mode — tickets are created and visits are "scheduled" with simulated responses.

To enable real Calendar:
1. Create a project at https://console.cloud.google.com
2. Enable Google Calendar API
3. Create OAuth 2.0 credentials → Desktop app → Download as `credentials.json`
4. Place `credentials.json` in the `05-it-helpdesk-agent/` directory
5. First launch triggers browser OAuth consent
