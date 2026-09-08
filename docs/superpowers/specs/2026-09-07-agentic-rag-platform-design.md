# Agentic RAG Portfolio Platform — Design Spec

**Status:** Approved for implementation planning
**Date:** 2026-09-07
**Owner:** Vinoth

## 1. Overview & Goals

Rebuild the existing 5-app RAG portfolio (`01-hr-policy-rag` through `05-it-helpdesk-agent`)
into a single, unified, professional-grade agentic AI platform. The platform must
simultaneously serve three goals:

1. **Job search** — demonstrate senior/staff-level AI engineering judgment, not just
   RAG plumbing.
2. **Freelance/consulting credibility** — prove the ability to ship governed,
   cost-controlled, production-shaped AI systems for real organizations.
3. **Product optionality** — leave the door open to spin any one app (most likely
   `05-it-helpdesk-agent`) into a real product later without a rewrite.

The defining differentiator versus a typical RAG portfolio: this platform treats
**governance, cost control, evaluation, and human oversight as first-class
architecture**, not afterthoughts. Every inference call is metered, every agentic
action with a side effect requires human approval, every retrieval/prompt change is
evaluated automatically, and quality gates block bad code from ever reaching `main`.

Budget posture: **free-tier infrastructure by default**, but the architecture itself
is enterprise-shaped (real provider abstraction, real audit trail, real CI gates) so
it scales without redesign if paid tiers are added later. Provider choice must not be
hard-coded to Groq — the platform must support swapping across multiple free-tier-
capable LLM and embedding providers via configuration only.

## 2. Non-Goals / Explicit Scope Boundaries

To keep this achievable in 8 weeks, the following are explicitly **out of scope** for
v1:

- Multi-tenant billing / real payment processing (RBAC is a stub: admin/user roles
  only, no org-level tenancy).
- A dedicated mobile app or native client.
- Fine-tuning or training any model — inference/RAG only.
- A fully staffed human review team for the "human approval gates" — the human is
  the platform owner (Vinoth) in a single-operator console, not a multi-reviewer
  workflow.
- "Zero bugs" as a literal, verifiable guarantee (see §14 — this is addressed
  honestly, not promised).

## 3. System Architecture

### 3.1 Monorepo layout

```
rag-portfolio/
├── apps/
│   ├── web/                  # Next.js frontend (Vercel)
│   └── api/                  # FastAPI gateway (Render)
│       ├── domains/
│       │   ├── hr_policy/
│       │   ├── contract_review/
│       │   ├── marketing_hub/
│       │   ├── techdocs/
│       │   └── it_helpdesk/
│       └── middleware/       # auth, spend-guard, audit-log, PII-scrub
├── packages/
│   ├── model_gateway/        # multi-provider inference abstraction
│   ├── agent_runtime/        # shared LangGraph supervisor pattern
│   ├── evals/                # golden sets + evaluators + CI gate runner
│   ├── governance/           # PII redaction, moderation, audit log, model cards
│   └── spend_guard/          # budget tracking + circuit breaker
├── infra/                    # IaC / deploy configs (vercel.json, CI)
└── docs/
```

(`render.yaml` itself must live at the repo root per Render's Blueprint convention,
not under `infra/`.)

Each of the 5 original apps becomes a **domain module** under `apps/api/domains/`,
reusing shared packages instead of duplicating logic (today's `shared/` module is the
seed for `packages/model_gateway`).

### 3.2 Component flow

```
Browser
  │
  ▼
Next.js (apps/web) ── one nav, shared design system, per-domain pages
  │  REST/JSON
  ▼
FastAPI Gateway (apps/api)
  │
  ├─► middleware chain: auth → spend_guard.pre_check → PII scrub (input) → audit log (start)
  │
  ▼
Domain router (e.g. hr_policy)
  │
  ├─► agent_runtime (only for domains that need multi-step orchestration: it_helpdesk, techdocs eval loop)
  ├─► retrieval (per-domain vector store: in-memory / Qdrant / Milvus Lite / Weaviate)
  ▼
model_gateway.complete(...) ── provider routing + fallback + cost estimate
  │
  ▼
governance.moderate_output() → PII scrub (output) → audit log (finish, cost, latency)
  │
  ▼
Response → Next.js
```

### 3.3 Domain services — right-sized complexity

Not every domain needs full agentic orchestration. Assignment:

| Domain | Orchestration | Rationale |
|---|---|---|
| hr_policy | Simple retrieval chain | Single-turn Q&A, no multi-step reasoning needed |
| contract_review | Retrieval + chat memory | Multi-turn but linear, no branching |
| marketing_hub | Retrieval + template routing | Deterministic routing, not agentic |
| techdocs | Retrieval + hybrid fusion + rerank | Pipeline, not agentic (no decision branching) |
| it_helpdesk | `agent_runtime` (LangGraph supervisor) | Only domain with real branching/tool-use decisions |

`agent_runtime` is a shared package, not duplicated per app, so it is exercised by
one domain today and reusable if a future domain needs it.

### 3.4 Agent runtime

Promotes the existing `05-it-helpdesk-agent` LangGraph supervisor pattern into
`packages/agent_runtime`:
- Typed shared state (Pydantic models, not dicts).
- Supervisor node routes to specialist nodes (RAG, Search, Tools).
- Every tool-invoking node that has a real-world side effect (ticket creation,
  calendar write) must route through the **human approval gate** (§8) before
  execution — this is enforced in the graph topology itself (an explicit
  `await_approval` node), not left to caller discipline.

## 4. Model Gateway (Inference Layer)

`packages/model_gateway` extends the existing `llm_factory.py` / `embedder_factory.py`
into a formal service:

- **Supported providers (LLM):** Groq, OpenAI, Anthropic, Google Gemini, Mistral,
  Cohere, HuggingFace Inference API, Ollama (local).
- **Supported providers (embeddings):** Ollama `nomic-embed-text`, Gemini
  `text-embedding-004`, HuggingFace `BAAI/bge-small-en-v1.5`, OpenAI embeddings.
- **Routing:** config-driven (`.env` / per-request override), with an explicit
  fallback chain: `primary → secondary → local (Ollama)`. Fallback triggers on
  provider error, rate-limit response, or timeout.
- **Every call wrapped with:**
  - Timeout (configurable per provider, default 30s).
  - Retry with exponential backoff (max 2 retries) — distinguished from the
    circuit breaker in §5, which handles *sustained* failure, not transient blips.
  - Pre-call cost estimator (token count × provider price table, updated as a
    versioned config file, not hard-coded).
  - Structured log emission: request id, provider, model, input/output tokens,
    estimated cost, latency, success/failure.
- Price table lives in `packages/model_gateway/pricing.yaml`, reviewed/updated
  manually — an explicit non-goal is live price-API integration for v1.
- **Prompt caching (cost-control, not just latency):** the gateway must use each
  provider's native prompt-caching mechanism where one exists — Anthropic prompt
  caching (`cache_control` breakpoints), Gemini context caching, and OpenAI's
  automatic prompt caching — for the parts of a request that repeat across calls:
  system prompts, domain instructions, and (for `techdocs`/`it_helpdesk`) the
  retrieved-context block when the same chunks recur across a session. Providers
  without a caching mechanism (Groq, Mistral, Cohere, HuggingFace Inference,
  Ollama-local) are called normally — caching is applied where supported, not
  simulated where it isn't. Cache hit/miss and cached-vs-fresh token counts are
  part of the structured log emission above, and the cost estimator (§4) and
  Spend Guard's pre-call check (§5) must price cached tokens at each provider's
  cached rate, not the fresh-token rate — otherwise the budget check
  over-estimates cost and triggers false downgrades/stops. Domain modules that
  compose prompts (all 5 domains, via `agent_runtime` or directly) must structure
  their prompts with the stable (system/instructions) portion first and the
  variable (per-query) portion last, since provider caching is prefix-based.

## 5. Spend Guard & Circuit Breaker

`packages/spend_guard` is middleware applied uniformly to every outbound model call
across all 5 domains.

**Budget enforcement:**
- Per-day and per-month `$` caps, configurable, defaulting to near-zero (e.g. $1/day)
  to match the free-tier-first posture.
- Before every call: estimate cost (via model_gateway's estimator), check against
  remaining budget for the period.
- If a call would exceed budget: **do not silently proceed**. Either (a) downgrade
  to a free/local provider (Ollama) if one is configured for that domain, or (b)
  hard-stop and return a clear, user-facing "budget exceeded" message — never a
  generic error.

**Circuit breaker (the "stuck" case):**
- Tracks consecutive provider errors per provider. N consecutive failures (default
  5) trips the breaker for that provider — no further calls routed to it until
  manual reset or a cooldown window (default 5 min) elapses.
- Tracks spend *velocity* (cost per minute). An abnormal spike (e.g. a runaway loop
  in an agent graph) trips a **global** breaker that halts all outbound model calls
  platform-wide, independent of the daily/monthly cap, and logs a critical alert.
- Breaker state is persisted (Postgres), not in-memory-only, so a process restart
  doesn't silently clear a tripped breaker.

**Budget/audit data store:** Postgres (Neon or Supabase free tier) — chosen over
SQLite because this is genuinely shared state across the FastAPI gateway's domains
and needs to survive redeploys; "enterprise style" calls for a real shared DB here.

## 6. Evaluation Framework & Quality Gates

`packages/evals` generalizes app 04's `FaithfulnessEvaluator`/`RelevancyEvaluator`
pattern to all 5 domains.

- **Golden sets:** a curated set of Q&A pairs per domain (10-30 to start,
  hand-written from real documents already in each app), each with expected
  retrieval characteristics (which source doc/section should be retrieved) and
  acceptable answer properties.
- **Evaluators:** Faithfulness (is the answer grounded in retrieved context),
  Relevancy (does retrieved context match the query), and a domain-specific
  correctness check where feasible.
- **Execution modes:**
  1. **On-demand** — run locally via CLI during development.
  2. **CI gate** — runs automatically on any PR touching retrieval, prompt, or
     domain logic files. **A PR is blocked from merging if any golden-set eval
     score regresses below its threshold** (default: faithfulness < 0.8,
     relevancy < 0.75). This is a hard gate, not advisory.
  3. **Prod shadow-eval** — a small sampled percentage of live queries are
     re-scored asynchronously post-response (never blocking the user-facing
     response) and logged to the observability dashboard (§10).

## 7. Governance, Ethics & Security

`packages/governance`:

- **PII detection/redaction:** applied on ingestion (documents indexed) and on
  output (responses shown to user). Regex-based rules for common PII (email,
  phone, SSN-like patterns) plus lightweight NER where feasible on free tier.
  Highest priority for `hr_policy`, `contract_review`, `it_helpdesk` (most likely
  to touch personal data).
- **Prompt-injection heuristics:** retrieved context is scanned for
  instruction-like patterns before being placed in the LLM prompt; flagged
  content is logged and stripped of imperative phrasing rather than blocking
  the whole response outright (fail soft, log hard).
- **Output moderation:** a policy/keyword check pass on generated output before
  it reaches the user; architected so a real moderation-model API can be
  swapped in later without changing the call site (same provider-abstraction
  discipline as the model gateway).
- **Audit log:** every query is recorded — query text (PII-scrubbed), retrieved
  source ids, provider used, tokens, cost, latency, and the final
  approve/execute decision for any agentic action. Immutable (append-only table,
  no update/delete path exposed).
- **RBAC (stub):** two roles, `admin` and `user`. Enough to demonstrate the
  concept exists as a first-class citizen, not a full permission system.
- **Model cards:** one markdown doc per domain — what data it's trained/indexed
  on, which model(s) it can run on, known limitations, and governance controls
  applied. Published alongside the platform (doubles as GTM content, §12).

## 8. Human Approval Gates

Any agentic action with a **real-world side effect** — currently: ticket creation
and calendar scheduling in `it_helpdesk` — must follow a strict
**propose → confirm → execute** flow:

1. Agent determines an action is needed and constructs the proposed action
   (e.g. "Create ticket: [summary], Priority: High").
2. The UI surfaces the proposed action explicitly to the user and **halts** —
   no execution happens without confirmation.
3. Only on explicit user confirmation does the action execute; audit log records
   both the proposal and the confirmation (or rejection).

This is enforced structurally in the `agent_runtime` graph (§3.4) via an explicit
`await_approval` node — a developer adding a new side-effecting tool cannot
accidentally bypass it, because the graph topology requires passing through that
node to reach any execution node.

## 9. Code Quality Standards

Applied uniformly across `apps/` and `packages/`:

- **Formatting/linting:** `ruff` + `black`, zero warnings tolerated in CI.
- **Type checking:** `mypy` in strict mode on `packages/` (shared code held to the
  highest bar since every domain depends on it); standard mode on `apps/api/domains/`.
- **Testing:** `pytest`. Unit tests for every shared package function with
  non-trivial logic; integration tests per domain covering the retrieval →
  generation → governance path end-to-end (with model calls mocked/recorded, not
  live, so CI doesn't burn budget). Coverage threshold enforced in CI: **80%
  minimum on `packages/`**, tracked but not blocking on `apps/api/domains/` (to
  avoid coverage theater on rapidly-iterating domain glue code).
- **CI pipeline order (GitHub Actions):** lint → type-check → unit tests →
  integration tests → eval quality gate (§6) → build → deploy (main branch only).
  Any stage failing blocks all subsequent stages and the merge.
- **Review gate:** every change goes through a PR, even solo — a self-review
  checklist plus an automated AI review pass (CodeRabbit, already available in
  this environment) before merge to `main`. This is the practical mechanism
  behind "no low-quality code merges" — see §14 for the honest limits of this
  claim.

## 10. Observability

- Structured JSON logs (already emitted by model_gateway, spend_guard, governance)
  aggregated into a lightweight metrics view.
- Dashboard (part of the Next.js app, admin-only route) surfacing: latency
  (p50/p95) per domain, cost per query and cumulative spend vs. budget, eval
  scores over time (from shadow-evals), error rate per provider, circuit breaker
  state.
- This dashboard is itself a differentiating showcase artifact — publishing live
  quality/cost metrics is unusual for a portfolio and doubles as a GTM proof point.

## 11. Infrastructure & Deployment (free-tier first)

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js on Vercel (free tier) | Native fit, zero-config previews |
| API | FastAPI, containerized, on Render (free tier) | Docker runtime via `render.yaml` Blueprint at repo root |
| Budget/audit/eval DB | Postgres via Neon or Supabase (free tier) | Real shared state, survives redeploys |
| Vector stores | Unchanged per-domain: in-memory (01/02), Qdrant (03), Milvus Lite (04), Weaviate embedded (05) | Preserves the deliberate variety already in the portfolio — itself a teaching point |
| CI/CD | GitHub Actions (free on public repos) | Standard, well-understood |
| Secrets | Provider-native secret managers (Vercel/Render env vars) | Never committed to git |
| Domain | Custom domain (~$10-12/yr) | Only realistic recurring cost; materially improves professional presentation |

**Amendment (2026-09-08):** API hosting changed from Fly.io to Render. Original
rationale for Fly.io: "Better scale-up story than Render if this ever needs to
grow." Actual reason for the swap: the user already held Render + Vercel
accounts and found Fly.io's pricing costly for this project's needs. The table
above has been updated to describe Render directly; this note preserves the
original decision trail rather than silently erasing it.

## 12. GTM Strategy

- **Positioning:** "A governed, cost-controlled agentic AI platform" — explicitly
  differentiated from generic RAG-chatbot portfolios by leading with governance,
  spend control, and evals rather than just retrieval tricks.
- **Content:** one architecture deep-dive post per pillar above (model gateway,
  spend guard, evals, governance, human-approval gates) — each doubles as both
  documentation and GTM, published on a blog/Substack/dev.to and cross-posted to
  LinkedIn.
- **Cadence:** weekly build-in-public updates matching the phased build plan
  (§13), each phase's completion becomes a post.
- **Freelance pitch:** leads with "I build governed, cost-controlled agentic AI
  systems for [HR/legal/IT] teams" — governance-as-differentiator rather than
  competing purely on RAG implementation speed.
- **Community/directory reach:** Show HN and r/LocalLLaMA (multi-provider +
  local-fallback angle fits both audiences), relevant AI-agent directories, and a
  Product Hunt launch once the platform is stable and polished.
- **Credibility proof points:** publish live eval scores, latency, and per-query
  cost from the observability dashboard (§10) — quantified, continuously-updated
  claims are rare in portfolios and hard to fake, which is exactly why they're
  persuasive.
- **Model cards** (§7) published per domain double as both a governance artifact
  and a content piece demonstrating responsible-AI practice.

## 13. Phased Build Plan (8 weeks)

| Week | Focus | Exit criteria |
|---|---|---|
| 1 | Monorepo scaffold, FastAPI gateway skeleton, CI pipeline (lint/type/test gates wired and green), minimal deploy live | Empty-but-live platform reachable at a public URL; CI blocks a deliberately broken PR |
| 2 | Model Gateway + Spend Guard, reference-implemented end-to-end on `hr_policy` | HR domain fully served through the gateway with budget enforcement and provider fallback demonstrated |
| 3 | Governance layer (PII redaction, audit log, moderation) + Evals package, applied to `hr_policy` and `contract_review` | Both domains have golden-set evals running in CI as a blocking gate; audit log populated |
| 4 | Human-approval-gate pattern generalized in `agent_runtime`; Next.js frontend shell (shared nav/design system, auth stub) wired to domains 1-2 | Unified UI live for 2 of 5 domains with real approval-gate UX demoed |
| 5 | Port `marketing_hub` and `techdocs` onto full stack (gateway, governance, evals) | 4 of 5 domains fully migrated and live |
| 6 | Port `it_helpdesk` — most complex, exercises `agent_runtime` and human approval gates on ticket/calendar actions | All 5 domains live on unified platform |
| 7 | Observability dashboard, security review pass, model cards published, final code-quality sweep (coverage, lint, type-check all green across the whole repo) | Dashboard live and public; no open lint/type/coverage gaps |
| 8 | GTM content production and launch: blog series, LinkedIn cadence, directory submissions, freelance outreach templates | First public launch posts published; platform stable under real traffic |

## 14. Risks & Honest Caveats

- **"No bugs ever" is not a literal engineering guarantee.** No amount of gating
  makes a system provably bug-free. What this spec commits to is genuine
  defense-in-depth — types, tests, evals, gates, and review — that catches the
  overwhelming majority of defects before merge. Framing this honestly in GTM
  content (as "rigorous quality gates," not "bug-free") is itself part of the
  professional credibility this platform is trying to build.
- **8 weeks is tight** for the full scope in §3-§10 across 5 domains. The plan
  sequences for an always-deployable, always-demoable platform at every week's
  boundary, so if time runs out, what exists at any checkpoint is still
  presentable (unlike a plan that only becomes demoable in week 8).
- **Free-tier infrastructure has real limits** (rate limits, cold starts, storage
  caps). The spend guard and provider fallback chain exist partly *because* of
  this — they are load-bearing, not decorative.
- **Solo-operator human approval gates** (§8, §2) are a meaningful safety pattern
  but are not equivalent to a multi-reviewer enterprise governance process — this
  spec is honest that it demonstrates the pattern at the scale appropriate for a
  single-owner platform, not that it replicates enterprise-scale governance
  staffing.

## 15. Success Criteria

- All 5 domains live on one unified, branded platform at a public URL.
- CI enforces lint, type-check, tests, coverage threshold, and eval quality gate
  as blocking merge gates — verifiable by pointing to a rejected PR.
- Spend guard and circuit breaker demonstrably prevent runaway cost in a
  deliberate test (documented in the observability dashboard or a linked demo).
- At least one agentic action (ticket creation) demonstrates the full
  propose→confirm→execute human approval flow.
- Observability dashboard publicly shows live cost, latency, and eval metrics.
- At least the first 2-3 GTM content pieces (architecture deep-dives) are
  published and linked from the platform itself.
