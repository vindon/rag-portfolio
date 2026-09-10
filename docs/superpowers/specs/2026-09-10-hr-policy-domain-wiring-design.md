# HR Policy Domain Wiring — Design Spec

**Supersedes-scope-of:** Master spec's Week 2 exit criterion (§13): *"HR domain
fully served through the gateway with budget enforcement and provider
fallback demonstrated."* This is the Plan 2c slice of that spec —
`docs/superpowers/specs/2026-09-07-agentic-rag-platform-design.md`.

## 1. Overview & Goals

`packages/model_gateway` and `packages/spend_guard` exist and are fully
tested, but nothing in `apps/api` calls them yet — every domain router
(`apps/api/src/gateway/domains/registry.py`) is a scaffold stub returning
`{"status": "scaffolded"}`. This plan wires the `hr_policy` domain into a
real, live, publicly reachable RAG endpoint that actually calls both
packages, backed by a real (not local-only) Postgres database, deployed to
Render.

**Goals:**
- Port the existing `01-hr-policy-rag/` CLI's retrieval logic (embed a
  markdown policy doc, retrieve top-k chunks, answer with citations) into
  `apps/api` as a real HTTP endpoint.
- Every call goes through `model_gateway.complete()`/`.embed()` (provider
  routing + fallback) and `spend_guard.precheck()`/`.record_success()`/
  `.record_failure()` (budget + circuit breaker), exactly as spec §5 requires.
- Provision a real Supabase Postgres project and point the deployed API at
  it — this is the first plan where `spend_guard`'s state is genuinely
  shared and durable in production, not just tested against local Postgres.
- Deploy to Render so the endpoint is live at a public URL.

## 2. Non-Goals / Explicit Scope Boundaries

- **No governance layer.** PII redaction, moderation, and audit logging are
  spec §7 / master-plan Week 3. Not built here.
- **No auth.** Spec's phased plan brings an "auth stub" in Week 4 alongside
  the frontend. The `/ask` endpoint is intentionally open — Spend Guard's
  hard budget cap *is* the abuse-containment mechanism for this plan, not a
  gap to patch with ad hoc rate-limiting.
- **No frontend.** Week 4. Verification here is via `curl`/integration
  tests against the deployed endpoint, not a UI.
- **No local-provider fallback in production.** Ollama cannot run on
  Render's free tier. `has_local_fallback=False` for every `hr_policy`
  call — an over-budget call hard-stops with a clear message (spec §5's
  explicit option (b)), it never silently downgrades.
- **No LlamaIndex.** Hand-rolled retrieval (chunk + embed + cosine
  similarity), not a port of the framework the standalone CLI used — see
  Decision Record below.
- **No persistent vector store.** In-memory index rebuilt at process start.
  One small markdown doc; cold-start re-embed cost is a few seconds.
- **No `packages/retrieval_lite` extraction.** This plan's retrieval code
  lives in `apps/api/src/gateway/domains/hr_policy/`. Extracting a shared
  package happens when a second domain (`contract_review`/`techdocs`,
  Week 5) actually needs the same logic — not speculatively now.

## 3. Decision Record (from brainstorming)

| Decision | Choice | Why |
|---|---|---|
| Budget-exceeded behavior | Hard-stop only, no local fallback | Ollama isn't deployable on Render free tier; spec's option (b) is the honest, simplest choice |
| Vector store | In-memory, rebuilt at startup | One small doc, domain is spec §3.3's "Simple retrieval chain" class, zero extra infra |
| Embedding provider (prod) | Gemini (`text-embedding-004`) | Generous free tier, already supported by `model_gateway`'s Gemini adapter |
| LLM provider (prod) | Groq primary, Gemini secondary | Matches existing `.env.example` convention |
| Retrieval implementation | Hand-rolled (chunk + embed + cosine), no LlamaIndex | Matches "Simple retrieval chain" complexity; avoids building LlamaIndex-adapter shims around `ModelGateway` for a framework it doesn't need |
| Supabase provisioning | Via Supabase MCP connector | Verifiable, no manual dashboard steps, schema applied and confirmed programmatically |
| Public exposure | Open endpoint, no added rate-limit | Spend Guard's cap is the intended abuse-containment mechanism; a demo endpoint hitting its own cap and returning a clear message *is* the feature working |

## 4. Architecture

### 4.1 Module layout

```
apps/api/src/gateway/domains/hr_policy/
├── __init__.py
├── retrieval.py     # chunking, embedding, in-memory index, cosine search
├── prompts.py        # HR-assistant prompt template (ported from 01-hr-policy-rag)
├── router.py          # POST /api/v1/hr_policy/ask
└── data/
    └── hr_policy.md   # copied from 01-hr-policy-rag/data/hr_policy.md
```

`apps/api/src/gateway/domains/registry.py` keeps serving the other 4 domains
(`contract_review`, `marketing_hub`, `techdocs`, `it_helpdesk`) as scaffold
stubs, unchanged. `apps/api/src/gateway/main.py`'s router-registration loop
special-cases `hr_policy` to mount the real router instead of the generic
scaffold one.

### 4.2 New addition to `packages/model_gateway`

Spec §5 requires budget checks to estimate cost "via model_gateway's
estimator" — today `pricing.estimate_cost()` only runs *after* a real call
returns actual token usage. A pre-call estimate needs a heuristic. Add one
public method to `ModelGateway`:

```python
def estimate_precheck_cost(self, messages: list[ChatMessage], *, max_tokens: int) -> float:
    """Conservative pre-call cost estimate for Spend Guard's precheck.

    Uses the primary provider in the fallback chain and a chars/4 input-token
    heuristic (no tokenizer dependency) with max_tokens as the worst-case
    output. Real cost after the call is always computed exactly from actual
    usage by complete()/embed() -- this estimate exists only to let Spend
    Guard reject or allow *before* spending anything.
    """
    chain = self._settings.llm_fallback_chain()
    if not chain:
        return 0.0
    provider_name = chain[0]
    config = self._settings.llm_providers[provider_name]
    input_tokens = sum(len(m.content) for m in messages) // 4
    return estimate_cost(
        provider=provider_name,
        model=config.model,
        input_tokens=input_tokens,
        output_tokens=max_tokens,
    )
```

This is additive (new public method, no existing signature changes) and
gets its own unit tests in `packages/model_gateway/tests/`.

### 4.3 Chunk data structure

```python
@dataclass(frozen=True)
class Chunk:
    header: str      # nearest markdown section heading, for citation
    text: str        # the chunk's paragraph text
    vector: list[float]
```

`retrieval.py` builds `list[Chunk]` at startup. `search(query_vector, k)`
returns the top-k `Chunk`s by cosine similarity, each paired with its score.
Carrying `header` alongside `text`/`vector` (rather than text-only) is what
makes the response's source citations meaningful instead of opaque chunk
indices — this was flagged during design review and is load-bearing for the
"source attribution" feature the original CLI has.

### 4.4 Startup (FastAPI lifespan) — graceful degradation

The naive version of this (build everything in `create_app()` at import
time, let any exception propagate) means a transient network blip or a
temporarily-invalid API key during cold start crashes the *entire* app,
including the other 4 domains' scaffold stubs and `/health` — taking down a
Render deployment over a problem in exactly one dependency. Flagged during
design review for the retrieval index; the same problem applies to
`create_spend_guard()` itself — with pool `min_size=1` (per the Week 2b fix
round), pool creation eagerly opens a real connection, so a transient
Supabase outage at cold start would crash the app the same way. Since
`spend_guard` is shared infrastructure across all 5 domains (spec §5), not
`hr_policy`-specific, both get the same graceful-degrade treatment, at the
app level:

```python
@dataclass
class LazyResource(Generic[T]):
    value: T | None
    build_error: str | None
    lock: asyncio.Lock


async def build_hr_policy_index(gateway: ModelGateway) -> RetrievalIndex:
    ...  # raises on failure; no swallowing here


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    gateway = ModelGateway()
    app.state.gateway = gateway

    app.state.spend_guard = LazyResource(value=None, build_error=None, lock=asyncio.Lock())
    try:
        app.state.spend_guard.value = await create_spend_guard()
    except Exception as exc:
        logger.critical("gateway.startup.spend_guard_init_failed error=%s", exc)
        app.state.spend_guard.build_error = str(exc)

    app.state.hr_policy_index = LazyResource(value=None, build_error=None, lock=asyncio.Lock())
    try:
        app.state.hr_policy_index.value = await build_hr_policy_index(gateway)
    except Exception as exc:
        logger.critical("hr_policy.startup.index_build_failed error=%s", exc)
        app.state.hr_policy_index.build_error = str(exc)

    yield
    if app.state.spend_guard.value is not None:
        await app.state.spend_guard.value.aclose()
```

The app always boots and `/health` always passes even if `spend_guard` or
`hr_policy`'s index failed to initialize. A shared helper resolves either
`LazyResource` the same way — try the cached value, else acquire the lock
and retry the build once, else raise `HTTPException(503, ...)`:

```python
async def resolve_lazy(
    resource: LazyResource[T], build: Callable[[], Awaitable[T]], *, error_detail: str
) -> T:
    if resource.value is not None:
        return resource.value
    async with resource.lock:
        if resource.value is not None:  # another request may have rebuilt while we waited
            return resource.value
        try:
            resource.value = await build()
            resource.build_error = None
        except Exception as exc:
            resource.build_error = str(exc)
            logger.critical("gateway.lazy_rebuild_failed error=%s", exc)
            raise HTTPException(status_code=503, detail=error_detail) from exc
    return resource.value


async def get_spend_guard(request: Request) -> SpendGuard:
    return await resolve_lazy(
        request.app.state.spend_guard,
        create_spend_guard,
        error_detail="Spend Guard is temporarily unavailable.",
    )
```

`router.py`'s dependency for the retrieval index reuses the exact same
`resolve_lazy` helper `get_spend_guard` uses:

```python
async def get_hr_policy_index(request: Request) -> RetrievalIndex:
    gateway: ModelGateway = request.app.state.gateway
    return await resolve_lazy(
        request.app.state.hr_policy_index,
        lambda: build_hr_policy_index(gateway),
        error_detail="hr_policy is temporarily unavailable",
    )
```

One lazy rebuild attempt per request while degraded, serialized by each
resource's own lock so concurrent requests during an outage don't all
hammer the same upstream (embedding API, or Postgres) at once. Once a
rebuild succeeds, every subsequent request uses the cached value again — no
per-request rebuild cost in the healthy path. `spend_guard` and the
retrieval index degrade and recover independently of each other.

### 4.5 Request flow — `POST /api/v1/hr_policy/ask`

Request: `{"question": str}`. Response (success):
`{"answer": str, "sources": [{"header": str, "excerpt": str, "relevance": float}], "provider_used": str}`.
Response (blocked/unavailable): `503` with
`{"detail": "<clear, specific reason>"}` — never a bare 500.

1. `index = await get_hr_policy_index(request)`, `spend_guard = await get_spend_guard(request)` (either may 503 per §4.4, independently).
2. `q_embed = await gateway.embed([question])` → query vector. (If this
   itself fails — e.g. Gemini is down — return 503 "hr_policy is
   temporarily unavailable"; do not attempt completion with no retrieval
   context.)
3. `chunks = index.search(q_embed, k=4)`.
4. `messages = build_prompt(question, chunks)` (via `prompts.py`).
5. `estimate = gateway.estimate_precheck_cost(messages, max_tokens=512)`.
6. `decision = await spend_guard.precheck(estimate, has_local_fallback=False)`.
   - `BLOCK_BUDGET_EXCEEDED` → `503 {"detail": "Daily budget for hr_policy has been reached. Try again tomorrow."}`
   - `BLOCK_GLOBAL_BREAKER` → `503 {"detail": "hr_policy is temporarily unavailable (circuit breaker open)."}`
   - `BLOCK_VELOCITY_SPIKE` → `503 {"detail": "hr_policy is temporarily unavailable (unusual spend velocity detected)."}`
   - `ALLOW` → continue. (`DOWNGRADE_TO_LOCAL` is unreachable here since
     `has_local_fallback=False` always yields `ALLOW` or a `BLOCK_*` from
     `precheck`'s own branching — asserted in tests, not just assumed.)
7. `outcome = await gateway.complete(messages, max_tokens=512)`.
   - Raises (whole fallback chain exhausted) → `spend_guard.record_failure(provider=<last attempted>)`, return `503 {"detail": "hr_policy is temporarily unavailable (all providers failed)."}`.
   - Succeeds → `spend_guard.record_success(outcome.estimated_cost_usd, domain="hr_policy", provider=<provider actually used>)`, build the response body from `outcome.result` + the retrieved `chunks`, return `200`.

### 4.6 Infrastructure

- Supabase project provisioned via the Supabase MCP connector (user
  authenticates it; agent provisions the project/database and runs
  `spend_guard.schema.apply_schema()` against it, then verifies the three
  tables exist).
- Render env vars (set in Render's dashboard, never committed):
  `DATABASE_URL` (Supabase connection string), `GROQ_API_KEY`,
  `GEMINI_API_KEY`, plus the existing `SPEND_GUARD_*` tuning vars (all have
  sane defaults per `packages/spend_guard/src/spend_guard/guard.py`, so only
  overrides need setting explicitly).
- `render.yaml` documents the required env var *names* (no values) so a
  fresh deploy fails fast and legibly if one is missing, rather than
  crashing opaquely at first request.
- `.env.example` gets an `hr_policy`-specific section noting which vars this
  domain needs locally to run against a real (or local) Postgres.

## 5. Error Handling Summary

Every failure mode in the request path returns a `503` with a specific,
user-facing `detail` string — spec §5's "never a generic error" requirement
— and is logged with enough context (`logger.warning`/`logger.critical`,
matching `spend_guard`'s existing logging conventions) to diagnose from
Render's logs alone. No failure mode crashes the process after startup;
startup itself degrades gracefully per §4.4 rather than crashing.

## 6. Testing Strategy

- `retrieval.py`: unit tests with fake embedding vectors (no network) —
  chunking correctness (headers attached to the right chunks), cosine
  similarity ranking correctness, top-k behavior.
- `model_gateway.estimate_precheck_cost`: unit tests against real
  `pricing.yaml` rows (same pattern as existing `pricing.py` tests), no
  network.
- `router.py`: integration tests using real local Postgres for
  `spend_guard` (consistent with every prior test in this codebase — no DB
  mocking) with `model_gateway`'s HTTP calls mocked at the transport layer
  (`httpx` mock transport, the same technique `model_gateway`'s own test
  suite already uses). Cases: happy path with citations in the response;
  budget-exceeded → 503 with the specific message; simulated provider
  fallback (primary fails, secondary succeeds) → 200 with `provider_used`
  reflecting the secondary; whole chain fails → 503 +
  `record_failure` called; lazy-rebuild-after-startup-failure path for
  *both* `LazyResource`s independently (start the app with a broken
  gateway/embedding call, confirm `/health` still passes and `/ask` 503s,
  then confirm a later successful rebuild recovers without a restart; same
  again for a `spend_guard` init failure); concurrent requests during a
  degraded state only trigger one rebuild per resource (lock behavior).
- No real network calls to Groq/Gemini/Supabase in CI — only in the
  deployed environment. Real Supabase is used only for the one-time
  provisioning + schema verification step, done directly by the agent via
  the MCP connector, not exercised by the test suite.

## 7. Success Criteria

- `curl` against the live Render URL's `POST /api/v1/hr_policy/ask` returns
  a real, cited answer to an HR-policy question.
- Deliberately exhausting the (tiny, default) daily budget produces a clear
  503 budget-exceeded response, not a crash or a generic error — this is
  the live demonstration spec §13's Week 2 exit criterion asks for.
- Provider fallback is demonstrably exercised (verified in tests with a
  simulated primary-provider failure; not necessarily provoked live in
  production, which would require deliberately breaking a real provider).
- All existing tests + new tests green, all gates (ruff/black/mypy strict)
  clean, zero suppressions — matching every prior plan in this project.
- `/health` and the other 4 domains' scaffold endpoints remain unaffected
  by a `spend_guard` init failure or an `hr_policy` index-build failure at
  startup — the app boots regardless, per §4.4.
