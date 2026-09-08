# Spend Guard (Week 2b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `packages/spend_guard` — a Postgres-backed budget enforcement + circuit breaker service, standalone and fully tested against a real local Postgres instance — plus two small, necessary extensions to the already-merged `packages/model_gateway` that Spend Guard depends on. This plan does NOT wire Spend Guard into any domain (that's Plan 2c, which also provisions the real Supabase instance and ports `hr_policy` to a live RAG endpoint), so this package is independently testable and mergeable on its own.

**Architecture:** Two small `model_gateway` changes come first (Tasks 1-2), since Spend Guard's design depends on them: `ModelGateway.embed()` gains cost/logging parity with `.complete()` (today embedding spend is invisible — a gap Spend Guard would otherwise inherit silently), and `ModelGateway.complete()` gains an optional `force_provider` parameter so Spend Guard can actually enact a "downgrade to local" decision (today the fallback chain is config-global; there's no way to force a single provider per-call). Then `packages/spend_guard` (Tasks 3-7): a `schema.sql` for three small tables (`budget_ledger`, `circuit_breaker_state`, `global_breaker_state`), pure async functions in `budget.py`/`circuit_breaker.py` that take an `asyncpg` connection, and a `SpendGuard` facade in `guard.py` that owns a connection pool and exposes `precheck()` / `record_success()` / `record_failure()`. Tests run against a **real local Postgres** (already installed on this machine at `postgresql://vinoth@localhost:5432/`) using a pool-acquired connection wrapped in a rolled-back transaction for isolation — no mocking of the database layer, matching how `model_gateway` avoided mocking HTTP semantics it didn't need to fake.

**Tech Stack:** Python 3.11+, asyncpg (async Postgres driver) + `asyncpg-stubs` (real type stubs — asyncpg itself ships none), pytest + anyio, ruff, black, mypy (strict).

**Spec:** `docs/superpowers/specs/2026-09-07-agentic-rag-platform-design.md` (§5 Spend Guard & Circuit Breaker is this plan's primary source; §4 Model Gateway for the two extensions; §9 Code Quality Standards for strict-mypy-on-packages/ and the "real dependencies over mocks where practical" precedent this plan follows for its DB tests).

## Global Constraints

- Python `>=3.11`; gate tools pinned exactly, matching every other package in this monorepo: `pytest==9.1.1`, `anyio==4.15.1`, `ruff==0.16.6`, `black==26.5.1`, `mypy==2.3.1`.
- `packages/` gets **strict mypy** (`strict = true`).
- `asyncpg` itself ships no type stubs (`import-untyped` under strict mypy) — do not add a blanket `ignore_missing_imports` or per-line `# type: ignore` for this. Instead, `asyncpg-stubs==0.31.3` (a real, actively maintained third-party stub package, verified in advance to type-check cleanly against this plan's code) is a **dev dependency** providing real types. This resolves the typing gap properly rather than suppressing it.
- **Typing detail verified in advance, load-bearing for every task in this plan:** `asyncpg.Pool.acquire()` yields `PoolConnectionProxy`, which is a *different, non-interchangeable* type from `asyncpg.Connection` under `asyncpg-stubs` (confirmed empirically before writing this plan — passing a `PoolConnectionProxy` where `Connection` is expected fails strict mypy with `arg-type`). Therefore: **every function in this package that takes a database connection parameter must type it as `asyncpg.pool.PoolConnectionProxy`, never `asyncpg.Connection`** — and test fixtures must also acquire connections via a `Pool` (never `asyncpg.connect()` directly), so tests and production code share the exact same type. This is not a style preference; typing it as `Connection` will fail strict mypy the moment a pool-acquired connection is passed in.
- No secrets or `.env` files ever committed. The local Postgres connection string used by tests contains no password (local trust/peer auth) — do not add one.
- Tests must run against a real Postgres, not a mock — this package's entire value is real transactional/persistence behavior (circuit breaker cooldowns, budget sums, `ON CONFLICT` upserts) that a mock would either fake incorrectly or not exercise at all.
- Any step that pushes to a remote Git host or deploys to a third-party platform is a visible, external action — pause for explicit go-ahead first, per the pattern established in Weeks 1 and 2a. (This plan has no such step — Postgres provisioning and deployment are Plan 2c's job, not this one's.)

---

### Task 1: Model Gateway — `EmbedOutcome` (cost/logging parity for `embed()`)

**Files:**
- Modify: `packages/model_gateway/src/model_gateway/gateway.py`
- Modify: `packages/model_gateway/src/model_gateway/__init__.py`
- Modify: `packages/model_gateway/tests/test_gateway.py`

**Interfaces:**
- Consumes: `model_gateway.pricing.estimate_cost` (already used by `complete()`).
- Produces: `model_gateway.gateway.EmbedOutcome(result: EmbeddingResult, estimated_cost_usd: float, attempted_providers: list[str])` — Task 6 (`SpendGuard.record_success`) and Plan 2c's `hr_policy` domain will consume `.estimated_cost_usd` and `.result.vectors`. `ModelGateway.embed(...)` now returns `EmbedOutcome` instead of a bare `EmbeddingResult` — this is a breaking change to the just-merged Week 2a API, acceptable because nothing outside this monorepo depends on it yet and nothing inside it calls `embed()` except this plan's own tests.

- [ ] **Step 1: Update the two existing embed tests for the new return shape, and add a cost-assertion test**

Modify `packages/model_gateway/tests/test_gateway.py`. Find `test_embed_returns_result_from_huggingface_provider` (currently ending with `result = await gateway.embed(["a", "b"])` then asserting on `result.vectors`/`result.provider`) and change the two assertions to unwrap `.result`:

```python
    outcome = await gateway.embed(["a", "b"])

    assert outcome.result.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert outcome.result.provider == "huggingface"
```

(Also rename the local variable from `result` to `outcome` in the call line itself, as shown above.)

Find `test_embed_falls_back_to_secondary_on_primary_failure` (currently ending with `result = await gateway.embed(["hi"])` then asserting `result.vectors == [[0.5, 0.6]]`) and change similarly:

```python
    outcome = await gateway.embed(["hi"])

    assert outcome.result.vectors == [[0.5, 0.6]]
    assert call_count["primary"] == 1
    assert call_count["secondary"] == 1
```

Add a new test asserting the cost estimate is real, immediately after those two (follow the existing file's import/fixture style — it already imports `pytest`, `httpx`, `ModelGateway`, `GatewaySettings`, `ProviderConfig`, `ChatMessage`, `ProviderError`, `Role` at the top; add nothing new to those imports for this test):

```python
@pytest.mark.anyio
async def test_embed_returns_cost_estimate_from_real_pricing_row() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 1_000_000}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {
        "openai": ProviderConfig("openai", "https://api.openai.com/v1", "k", "text-embedding-3-small"),
    }
    settings = GatewaySettings(
        llm_primary="",
        llm_secondary="",
        llm_local="",
        embed_primary="openai",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        retry_base_delay_seconds=0.001,
        llm_providers={},
        embed_providers=providers,
    )
    gateway = ModelGateway(settings, client=client)

    outcome = await gateway.embed(["hi"])

    assert outcome.attempted_providers == ["openai"]
    assert outcome.estimated_cost_usd == pytest.approx(0.02)
```

(This uses `openai`/`text-embedding-3-small`'s real `pricing.yaml` row — `input_per_million: 0.02` — with 1,000,000 prompt tokens, so the expected cost is exactly `$0.02`; this is the same "use a real provider/model pair, not a placeholder" discipline Task 8 of the Week 2a plan used.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/model_gateway && .venv/bin/pytest tests/test_gateway.py -v` (reuse the existing venv from Week 2a — it's already set up in this worktree).
Expected: the two modified tests FAIL (they call `.vectors`/`.provider` on what is still a plain `EmbeddingResult`, so `outcome.result` doesn't exist yet — actually, since you haven't changed `embed()` yet, the variable is still named `result` in the test file at this point and calling `.result` on it will fail); the new test FAILS or errors since `outcome.estimated_cost_usd`/`outcome.attempted_providers` don't exist on a bare `EmbeddingResult`.

- [ ] **Step 3: Modify `gateway.py`**

In `packages/model_gateway/src/model_gateway/gateway.py`:

Add the `EmbedOutcome` dataclass right after the existing `ChatOutcome` dataclass:

```python
@dataclass
class EmbedOutcome:
    result: EmbeddingResult
    estimated_cost_usd: float
    attempted_providers: list[str]
```

Replace the entire `embed()` method with:

```python
    async def embed(self, texts: list[str]) -> EmbedOutcome:
        chain = self._settings.embed_fallback_chain()
        if not chain:
            raise ProviderError("model_gateway", "no embedding providers configured")

        attempted: list[str] = []
        last_error: Exception | None = None
        for provider_name in chain:
            attempted.append(provider_name)
            config = self._settings.embed_providers[provider_name]
            adapter = _build_embed_adapter(
                config, timeout=self._settings.timeout_seconds, client=self._client
            )

            async def _call(
                a: EmbeddingProvider = adapter, c: ProviderConfig = config
            ) -> EmbeddingResult:
                return await a.embed(texts, model=c.model)

            try:
                embed_result = await call_with_retry(
                    _call,
                    max_retries=self._settings.max_retries,
                    base_delay_seconds=self._settings.retry_base_delay_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "model_gateway.embed.failed provider=%s error=%s", provider_name, exc
                )
                last_error = exc
                continue

            cost = estimate_cost(
                provider=provider_name,
                model=config.model,
                input_tokens=embed_result.usage.input_tokens,
                output_tokens=embed_result.usage.output_tokens,
                cached_input_tokens=embed_result.usage.cached_input_tokens,
            )
            logger.info(
                "model_gateway.embed.success provider=%s model=%s input_tokens=%d "
                "estimated_cost_usd=%.6f latency_ms=%.1f",
                provider_name,
                config.model,
                embed_result.usage.input_tokens,
                cost,
                embed_result.latency_ms,
            )
            return EmbedOutcome(
                result=embed_result, estimated_cost_usd=cost, attempted_providers=attempted
            )

        raise ProviderError(
            "model_gateway", f"all embedding providers failed: {attempted}"
        ) from last_error
```

(Note this mirrors `complete()`'s structure exactly, including switching from the prior version's early-`return embed_result` inside the loop to building the `attempted` list and returning `EmbedOutcome` after the cost/logging block — same shape as `complete()`, for consistency.)

Modify `packages/model_gateway/src/model_gateway/__init__.py` to also export `EmbedOutcome`:

```python
from model_gateway.gateway import ChatOutcome, EmbedOutcome, ModelGateway
from model_gateway.types import ChatMessage, Role

__all__ = ["ChatMessage", "ChatOutcome", "EmbedOutcome", "ModelGateway", "Role"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_gateway.py -v` (from `packages/model_gateway/`)
Expected: all embed tests pass, including the new cost-assertion test. Full suite: `.venv/bin/pytest -v` should show 37 passed (36 existing + 1 new).

- [ ] **Step 5: Run quality gates locally**

Run: `.venv/bin/ruff check . && .venv/bin/black --check . && .venv/bin/mypy src` (from `packages/model_gateway/`)
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/model_gateway/src/model_gateway/gateway.py packages/model_gateway/src/model_gateway/__init__.py packages/model_gateway/tests/test_gateway.py
git commit -m "feat(model-gateway): add EmbedOutcome for cost/logging parity with complete()"
```

---

### Task 2: Model Gateway — `force_provider` on `complete()` (enables downgrade)

**Files:**
- Modify: `packages/model_gateway/src/model_gateway/gateway.py`
- Modify: `packages/model_gateway/tests/test_gateway.py`

**Interfaces:**
- Produces: `ModelGateway.complete(messages, *, temperature=0.1, max_tokens=1024, force_provider: str | None = None) -> ChatOutcome` — when `force_provider` is set, the fallback chain becomes exactly `[force_provider]` (bypassing the configured primary/secondary/local sequence), still going through the same retry-then-fail logic. Raises `ProviderError` if `force_provider` names a provider not present in `settings.llm_providers`. Plan 2c's `SpendGuard`-integrated `hr_policy` domain will use this to enact a "downgrade to local Ollama" decision.

- [ ] **Step 1: Write the failing tests**

Add to `packages/model_gateway/tests/test_gateway.py` (after the existing `complete()` tests, before the `embed()` tests — match the file's existing section ordering):

```python
@pytest.mark.anyio
async def test_complete_with_force_provider_bypasses_configured_chain() -> None:
    calls = {"configured_primary": 0, "forced": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "configured-primary" in str(request.url):
            calls["configured_primary"] += 1
            return httpx.Response(200, json=_SUCCESS_BODY)
        calls["forced"] += 1
        return httpx.Response(200, json=_SUCCESS_BODY)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {
        "configured_primary": ProviderConfig(
            "configured_primary", "https://configured-primary.example/v1", "k", "m"
        ),
        "forced_local": ProviderConfig("forced_local", "https://forced-local.example/v1", "k", "m"),
    }
    settings = _settings_with(providers, secondary="")
    gateway = ModelGateway(settings, client=client)

    outcome = await gateway.complete(
        [ChatMessage(role=Role.USER, content="hi")], force_provider="forced_local"
    )

    assert outcome.attempted_providers == ["forced_local"]
    assert calls["configured_primary"] == 0
    assert calls["forced"] == 1


@pytest.mark.anyio
async def test_complete_with_unknown_force_provider_raises() -> None:
    providers = {
        "primary": ProviderConfig("primary", "https://primary.example/v1", "k", "m"),
    }
    settings = _settings_with(providers)
    gateway = ModelGateway(settings)

    with pytest.raises(ProviderError):
        await gateway.complete(
            [ChatMessage(role=Role.USER, content="hi")], force_provider="nonexistent"
        )
```

(`_settings_with` and `_SUCCESS_BODY` are the existing helpers already defined near the top of this test file — reuse them, don't redefine.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_gateway.py -v -k force_provider` (from `packages/model_gateway/`)
Expected: FAIL — `complete()` doesn't accept a `force_provider` keyword yet.

- [ ] **Step 3: Modify `complete()`**

In `packages/model_gateway/src/model_gateway/gateway.py`, change the `complete()` signature and its chain-resolution line:

```python
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        force_provider: str | None = None,
    ) -> ChatOutcome:
        if force_provider is not None:
            if force_provider not in self._settings.llm_providers:
                raise ProviderError(
                    "model_gateway", f"force_provider '{force_provider}' is not configured"
                )
            chain = [force_provider]
        else:
            chain = self._settings.llm_fallback_chain()
        if not chain:
            raise ProviderError("model_gateway", "no LLM providers configured")
```

(Everything below this in `complete()` — the `attempted`/`last_error` loop — is unchanged; it already just iterates whatever `chain` resolves to.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_gateway.py -v` (from `packages/model_gateway/`)
Expected: all pass. Full suite: `.venv/bin/pytest -v` should show 39 passed (37 from Task 1 + 2 new).

- [ ] **Step 5: Run quality gates locally**

Run: `.venv/bin/ruff check . && .venv/bin/black --check . && .venv/bin/mypy src` (from `packages/model_gateway/`)
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/model_gateway/src/model_gateway/gateway.py packages/model_gateway/tests/test_gateway.py
git commit -m "feat(model-gateway): add force_provider to complete() for downgrade support"
```

---

### Task 3: `packages/spend_guard` skeleton, schema, and test database bootstrap

**Files:**
- Create: `packages/spend_guard/pyproject.toml`
- Create: `packages/spend_guard/src/spend_guard/__init__.py`
- Create: `packages/spend_guard/src/spend_guard/schema.sql`
- Create: `packages/spend_guard/tests/conftest.py`
- Test: `packages/spend_guard/tests/test_schema_bootstrap.py`

**Interfaces:**
- Produces: `spend_guard/schema.sql` — the three tables (`budget_ledger`, `circuit_breaker_state`, `global_breaker_state`) every later task's SQL queries assume exist.
- Produces: `tests/conftest.py`'s `TEST_DATABASE_URL` (module constant), `anyio_backend` fixture, and a `pytest_configure` hook that creates the test database (if missing) and applies the schema once per test session — every later task's tests rely on this running first, automatically (no manual setup step).

- [ ] **Step 1: Write the package config**

Create `packages/spend_guard/pyproject.toml`:

```toml
[project]
name = "spend-guard"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "asyncpg>=0.30",
]

[project.optional-dependencies]
dev = [
    "pytest==9.1.1",
    "anyio==4.15.1",
    "ruff==0.16.6",
    "black==26.5.1",
    "mypy==2.3.1",
    "asyncpg-stubs==0.31.3",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/spend_guard"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.mypy]
python_version = "3.11"
strict = true
mypy_path = "src"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create empty `packages/spend_guard/src/spend_guard/__init__.py`.

- [ ] **Step 2: Write the schema**

Create `packages/spend_guard/src/spend_guard/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS budget_ledger (
    id BIGSERIAL PRIMARY KEY,
    domain TEXT NOT NULL,
    provider TEXT NOT NULL,
    cost_usd NUMERIC(12, 6) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_budget_ledger_created_at ON budget_ledger (created_at);

CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    provider TEXT PRIMARY KEY,
    consecutive_failures INT NOT NULL DEFAULT 0,
    tripped_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS global_breaker_state (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    tripped_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- [ ] **Step 3: Write the failing test**

Create `packages/spend_guard/tests/test_schema_bootstrap.py`. Note: this test file reads `TEST_DATABASE_URL` from the environment directly (same default as `conftest.py`) rather than importing it from `conftest` — `tests/` has no `__init__.py`, so under pytest's default import mode `tests.conftest` is not an importable dotted path from a sibling test module. `conftest.py`'s fixtures (like `anyio_backend`) are still auto-discovered by pytest normally; only the plain constant needs this small, deliberate duplication. Every task's test file in this plan follows the same pattern — copy it exactly, don't try to import across test files.

```python
from __future__ import annotations

import os

import asyncpg
import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vinoth@localhost:5432/spend_guard_test"
)


@pytest.mark.anyio
async def test_schema_tables_exist_after_bootstrap() -> None:
    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=1)
    try:
        async with pool.acquire() as conn:
            tables = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY($1)",
                ["budget_ledger", "circuit_breaker_state", "global_breaker_state"],
            )
        names = {row["table_name"] for row in tables}
        assert names == {"budget_ledger", "circuit_breaker_state", "global_breaker_state"}
    finally:
        await pool.close()
```

- [ ] **Step 4: Run test to verify it fails**

Run:
```bash
cd packages/spend_guard
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```
Expected: FAIL — `tests.conftest` (specifically `TEST_DATABASE_URL` and the bootstrap hook) doesn't exist yet, so this errors at collection.

- [ ] **Step 5: Write conftest.py**

Create `packages/spend_guard/tests/conftest.py`:

```python
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest

_SCHEMA_PATH = Path(__file__).parent.parent / "src" / "spend_guard" / "schema.sql"

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vinoth@localhost:5432/spend_guard_test"
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _ensure_database_exists() -> None:
    base, _, db_name = TEST_DATABASE_URL.rpartition("/")
    admin_dsn = f"{base}/postgres"
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


async def _apply_schema() -> None:
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await conn.execute(_SCHEMA_PATH.read_text())
    finally:
        await conn.close()


def pytest_configure(config: pytest.Config) -> None:
    asyncio.run(_ensure_database_exists())
    asyncio.run(_apply_schema())
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest -v`
Expected: PASS. (This connects to the local Postgres server already running on this machine at `localhost:5432`, creates a `spend_guard_test` database if one doesn't already exist there — it won't collide with any existing database on that server, e.g. an unrelated `telecom_copilot` database was observed there during planning and must not be touched — and applies the schema.)

- [ ] **Step 7: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean. (`mypy src` only — the schema-bootstrap test itself isn't under `strict` package-code scrutiny the same way, but keep it clean regardless; if `mypy` is invoked against `tests/` too and complains about the test file, that's fine to fix like normal — the `[tool.mypy]` config above only sets `mypy_path`, not `files`, so running `mypy src` scopes to source only, matching every other package's Task-1-style local verification convention in this monorepo.)

- [ ] **Step 8: Commit**

```bash
git add packages/spend_guard/pyproject.toml packages/spend_guard/src packages/spend_guard/tests
git commit -m "feat(spend-guard): add package skeleton, DB schema, and test database bootstrap"
```

---

### Task 4: `budget.py` — budget status and spend recording

**Files:**
- Create: `packages/spend_guard/src/spend_guard/budget.py`
- Test: `packages/spend_guard/tests/test_budget.py`

**Interfaces:**
- Consumes: `spend_guard.schema.sql`'s `budget_ledger` table (Task 3).
- Produces: `spend_guard.budget.BudgetStatus(spent_today_usd, spent_this_month_usd, daily_cap_usd, monthly_cap_usd)` with a `.within_budget` property; `spend_guard.budget.get_budget_status(conn: asyncpg.pool.PoolConnectionProxy, *, daily_cap_usd: float, monthly_cap_usd: float) -> BudgetStatus`; `spend_guard.budget.record_spend(conn: asyncpg.pool.PoolConnectionProxy, *, domain: str, provider: str, cost_usd: float) -> None` — Task 6's `SpendGuard` facade calls both.

- [ ] **Step 1: Write the failing test**

Create `packages/spend_guard/tests/test_budget.py`:

```python
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest

from spend_guard.budget import get_budget_status, record_spend

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vinoth@localhost:5432/spend_guard_test"
)


@pytest.fixture
async def db_conn() -> AsyncIterator[asyncpg.pool.PoolConnectionProxy]:
    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=1)
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            yield conn
        finally:
            await tx.rollback()
    await pool.close()


@pytest.mark.anyio
async def test_get_budget_status_with_no_spend_is_zero(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    status = await get_budget_status(db_conn, daily_cap_usd=1.0, monthly_cap_usd=20.0)

    assert status.spent_today_usd == 0.0
    assert status.spent_this_month_usd == 0.0
    assert status.within_budget is True


@pytest.mark.anyio
async def test_record_spend_is_reflected_in_status(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    await record_spend(db_conn, domain="hr_policy", provider="groq", cost_usd=0.30)
    await record_spend(db_conn, domain="hr_policy", provider="groq", cost_usd=0.25)

    status = await get_budget_status(db_conn, daily_cap_usd=1.0, monthly_cap_usd=20.0)

    assert status.spent_today_usd == pytest.approx(0.55)
    assert status.spent_this_month_usd == pytest.approx(0.55)
    assert status.within_budget is True


@pytest.mark.anyio
async def test_within_budget_is_false_once_daily_cap_exceeded(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    await record_spend(db_conn, domain="hr_policy", provider="groq", cost_usd=1.50)

    status = await get_budget_status(db_conn, daily_cap_usd=1.0, monthly_cap_usd=20.0)

    assert status.within_budget is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_budget.py -v` (from `packages/spend_guard/`, with `.venv` activated)
Expected: FAIL — `spend_guard.budget` doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Create `packages/spend_guard/src/spend_guard/budget.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class BudgetStatus:
    spent_today_usd: float
    spent_this_month_usd: float
    daily_cap_usd: float
    monthly_cap_usd: float

    @property
    def within_budget(self) -> bool:
        return (
            self.spent_today_usd < self.daily_cap_usd
            and self.spent_this_month_usd < self.monthly_cap_usd
        )


async def get_budget_status(
    conn: asyncpg.pool.PoolConnectionProxy, *, daily_cap_usd: float, monthly_cap_usd: float
) -> BudgetStatus:
    spent_today = await conn.fetchval(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM budget_ledger "
        "WHERE created_at >= date_trunc('day', now())"
    )
    spent_month = await conn.fetchval(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM budget_ledger "
        "WHERE created_at >= date_trunc('month', now())"
    )
    return BudgetStatus(
        spent_today_usd=float(spent_today),
        spent_this_month_usd=float(spent_month),
        daily_cap_usd=daily_cap_usd,
        monthly_cap_usd=monthly_cap_usd,
    )


async def record_spend(
    conn: asyncpg.pool.PoolConnectionProxy, *, domain: str, provider: str, cost_usd: float
) -> None:
    await conn.execute(
        "INSERT INTO budget_ledger (domain, provider, cost_usd) VALUES ($1, $2, $3)",
        domain,
        provider,
        cost_usd,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_budget.py -v`
Expected: all 3 PASS.

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/spend_guard/src/spend_guard/budget.py packages/spend_guard/tests/test_budget.py
git commit -m "feat(spend-guard): add budget status and spend recording"
```

---

### Task 5: `circuit_breaker.py` — per-provider trip/cooldown and global spend velocity

**Files:**
- Create: `packages/spend_guard/src/spend_guard/circuit_breaker.py`
- Test: `packages/spend_guard/tests/test_circuit_breaker.py`

**Interfaces:**
- Consumes: `spend_guard.schema.sql`'s `circuit_breaker_state`/`global_breaker_state` tables (Task 3), `budget_ledger` (Task 3, for the velocity query).
- Produces: `spend_guard.circuit_breaker.BreakerStatus(tripped: bool, consecutive_failures: int)`; `record_provider_failure(conn, *, provider, threshold) -> BreakerStatus`; `record_provider_success(conn, *, provider) -> None`; `is_provider_tripped(conn, *, provider, cooldown_seconds) -> bool`; `get_spend_velocity(conn) -> float` (dollars spent in the last 60 seconds); `trip_global_breaker(conn) -> None`; `is_global_breaker_tripped(conn, *, cooldown_seconds) -> bool` — Task 6's `SpendGuard` facade calls all of these.

- [ ] **Step 1: Write the failing test**

Create `packages/spend_guard/tests/test_circuit_breaker.py`:

```python
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest

from spend_guard.budget import record_spend
from spend_guard.circuit_breaker import (
    get_spend_velocity,
    is_global_breaker_tripped,
    is_provider_tripped,
    record_provider_failure,
    record_provider_success,
    trip_global_breaker,
)

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vinoth@localhost:5432/spend_guard_test"
)


@pytest.fixture
async def db_conn() -> AsyncIterator[asyncpg.pool.PoolConnectionProxy]:
    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=1)
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            yield conn
        finally:
            await tx.rollback()
    await pool.close()


@pytest.mark.anyio
async def test_provider_trips_after_threshold_consecutive_failures(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    for _ in range(4):
        status = await record_provider_failure(db_conn, provider="groq", threshold=5)
        assert status.tripped is False

    status = await record_provider_failure(db_conn, provider="groq", threshold=5)

    assert status.tripped is True
    assert status.consecutive_failures == 5
    assert await is_provider_tripped(db_conn, provider="groq", cooldown_seconds=300) is True


@pytest.mark.anyio
async def test_provider_success_resets_consecutive_failures(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    for _ in range(3):
        await record_provider_failure(db_conn, provider="groq", threshold=5)

    await record_provider_success(db_conn, provider="groq")

    status = await record_provider_failure(db_conn, provider="groq", threshold=5)
    assert status.consecutive_failures == 1


@pytest.mark.anyio
async def test_untripped_provider_is_not_tripped(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    assert await is_provider_tripped(db_conn, provider="never_seen", cooldown_seconds=300) is False


@pytest.mark.anyio
async def test_spend_velocity_reflects_recent_spend(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    assert await get_spend_velocity(db_conn) == 0.0

    await record_spend(db_conn, domain="hr_policy", provider="groq", cost_usd=0.75)

    assert await get_spend_velocity(db_conn) == pytest.approx(0.75)


@pytest.mark.anyio
async def test_global_breaker_trips_and_reports_tripped(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    assert await is_global_breaker_tripped(db_conn, cooldown_seconds=300) is False

    await trip_global_breaker(db_conn)

    assert await is_global_breaker_tripped(db_conn, cooldown_seconds=300) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_circuit_breaker.py -v` (from `packages/spend_guard/`)
Expected: FAIL — `spend_guard.circuit_breaker` doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Create `packages/spend_guard/src/spend_guard/circuit_breaker.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import asyncpg


@dataclass(frozen=True)
class BreakerStatus:
    tripped: bool
    consecutive_failures: int


async def record_provider_failure(
    conn: asyncpg.pool.PoolConnectionProxy, *, provider: str, threshold: int
) -> BreakerStatus:
    row = await conn.fetchrow(
        """
        INSERT INTO circuit_breaker_state (provider, consecutive_failures, updated_at)
        VALUES ($1, 1, now())
        ON CONFLICT (provider) DO UPDATE
        SET consecutive_failures = circuit_breaker_state.consecutive_failures + 1,
            updated_at = now()
        RETURNING consecutive_failures
        """,
        provider,
    )
    assert row is not None
    failures = int(row["consecutive_failures"])
    tripped = failures >= threshold
    if tripped:
        await conn.execute(
            "UPDATE circuit_breaker_state SET tripped_at = now() "
            "WHERE provider = $1 AND tripped_at IS NULL",
            provider,
        )
    return BreakerStatus(tripped=tripped, consecutive_failures=failures)


async def record_provider_success(conn: asyncpg.pool.PoolConnectionProxy, *, provider: str) -> None:
    await conn.execute(
        """
        INSERT INTO circuit_breaker_state (provider, consecutive_failures, tripped_at, updated_at)
        VALUES ($1, 0, NULL, now())
        ON CONFLICT (provider) DO UPDATE
        SET consecutive_failures = 0, tripped_at = NULL, updated_at = now()
        """,
        provider,
    )


async def is_provider_tripped(
    conn: asyncpg.pool.PoolConnectionProxy, *, provider: str, cooldown_seconds: int
) -> bool:
    row = await conn.fetchrow(
        "SELECT tripped_at FROM circuit_breaker_state WHERE provider = $1", provider
    )
    if row is None or row["tripped_at"] is None:
        return False
    tripped_at: datetime = row["tripped_at"]
    return datetime.now(timezone.utc) - tripped_at < timedelta(seconds=cooldown_seconds)


async def get_spend_velocity(conn: asyncpg.pool.PoolConnectionProxy) -> float:
    spent_last_minute = await conn.fetchval(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM budget_ledger "
        "WHERE created_at >= now() - interval '1 minute'"
    )
    return float(spent_last_minute)


async def trip_global_breaker(conn: asyncpg.pool.PoolConnectionProxy) -> None:
    await conn.execute(
        """
        INSERT INTO global_breaker_state (id, tripped_at, updated_at)
        VALUES (1, now(), now())
        ON CONFLICT (id) DO UPDATE SET tripped_at = now(), updated_at = now()
        """
    )


async def is_global_breaker_tripped(
    conn: asyncpg.pool.PoolConnectionProxy, *, cooldown_seconds: int
) -> bool:
    row = await conn.fetchrow("SELECT tripped_at FROM global_breaker_state WHERE id = 1")
    if row is None or row["tripped_at"] is None:
        return False
    tripped_at: datetime = row["tripped_at"]
    return datetime.now(timezone.utc) - tripped_at < timedelta(seconds=cooldown_seconds)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_circuit_breaker.py -v`
Expected: all 5 PASS.

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/spend_guard/src/spend_guard/circuit_breaker.py packages/spend_guard/tests/test_circuit_breaker.py
git commit -m "feat(spend-guard): add per-provider circuit breaker and global spend velocity"
```

---

### Task 6: `guard.py` — the `SpendGuard` facade

**Files:**
- Create: `packages/spend_guard/src/spend_guard/guard.py`
- Modify: `packages/spend_guard/src/spend_guard/__init__.py`
- Test: `packages/spend_guard/tests/test_guard.py`

**Interfaces:**
- Consumes: everything from Tasks 4-5 (`budget.{get_budget_status, record_spend}`, `circuit_breaker.*`).
- Produces: `spend_guard.guard.SpendDecision` (str Enum: `ALLOW`, `DOWNGRADE_TO_LOCAL`, `BLOCK`); `spend_guard.guard.SpendGuard` with `precheck(estimated_cost_usd, *, has_local_fallback=True) -> SpendDecision`, `record_success(cost_usd, *, domain, provider) -> None`, `record_failure(*, provider) -> bool` (returns whether that provider is now tripped), `is_provider_available(*, provider) -> bool`, `aclose() -> None`; `spend_guard.guard.create_spend_guard(dsn=None, *, env=None) -> SpendGuard` (env-driven factory) — Plan 2c's `hr_policy` domain wiring is the consumer, mirroring how `apps/api`'s lifespan will construct one `ModelGateway` and one `SpendGuard` at startup and close both at shutdown.

- [ ] **Step 1: Write the failing tests**

Create `packages/spend_guard/tests/test_guard.py`:

```python
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest

from spend_guard.guard import SpendDecision, SpendGuard, create_spend_guard

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vinoth@localhost:5432/spend_guard_test"
)


@pytest.fixture
async def clean_db() -> AsyncIterator[None]:
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await conn.execute("TRUNCATE budget_ledger, circuit_breaker_state, global_breaker_state")
        yield
    finally:
        await conn.execute("TRUNCATE budget_ledger, circuit_breaker_state, global_breaker_state")
        await conn.close()


@pytest.fixture
async def guard(clean_db: None) -> AsyncIterator[SpendGuard]:
    # Velocity threshold is deliberately high (effectively disabled) for this shared
    # fixture, so budget-cap and circuit-breaker tests aren't accidentally tripped by
    # the velocity check (which runs *before* the budget check inside precheck()) when
    # they record a single spend close to the daily cap. test_precheck_blocks_when_
    # velocity_threshold_exceeded below builds its own guard with a low threshold
    # instead of using this fixture, to isolate that behavior.
    g = await create_spend_guard(
        TEST_DATABASE_URL,
        env={
            "SPEND_GUARD_DAILY_CAP_USD": "1.0",
            "SPEND_GUARD_MONTHLY_CAP_USD": "20.0",
            "SPEND_GUARD_CIRCUIT_BREAKER_THRESHOLD": "3",
            "SPEND_GUARD_CIRCUIT_BREAKER_COOLDOWN_SECONDS": "300",
            "SPEND_GUARD_VELOCITY_THRESHOLD_USD_PER_MINUTE": "100.0",
        },
    )
    try:
        yield g
    finally:
        await g.aclose()


@pytest.mark.anyio
async def test_precheck_allows_when_within_budget(guard: SpendGuard) -> None:
    decision = await guard.precheck(0.10)
    assert decision == SpendDecision.ALLOW


@pytest.mark.anyio
async def test_precheck_downgrades_when_over_daily_cap_and_local_fallback_available(
    guard: SpendGuard,
) -> None:
    await guard.record_success(0.95, domain="hr_policy", provider="groq")

    decision = await guard.precheck(0.10, has_local_fallback=True)

    assert decision == SpendDecision.DOWNGRADE_TO_LOCAL


@pytest.mark.anyio
async def test_precheck_blocks_when_over_daily_cap_and_no_local_fallback(
    guard: SpendGuard,
) -> None:
    await guard.record_success(0.95, domain="hr_policy", provider="groq")

    decision = await guard.precheck(0.10, has_local_fallback=False)

    assert decision == SpendDecision.BLOCK


@pytest.mark.anyio
async def test_precheck_blocks_when_velocity_threshold_exceeded(clean_db: None) -> None:
    # Uses its own guard (not the shared `guard` fixture) so the low velocity
    # threshold here doesn't leak into the budget-cap tests above, and a high
    # daily cap so this test's spend can never be mistaken for a budget-cap trip.
    g = await create_spend_guard(
        TEST_DATABASE_URL,
        env={
            "SPEND_GUARD_DAILY_CAP_USD": "100.0",
            "SPEND_GUARD_MONTHLY_CAP_USD": "1000.0",
            "SPEND_GUARD_CIRCUIT_BREAKER_THRESHOLD": "3",
            "SPEND_GUARD_CIRCUIT_BREAKER_COOLDOWN_SECONDS": "300",
            "SPEND_GUARD_VELOCITY_THRESHOLD_USD_PER_MINUTE": "0.50",
        },
    )
    try:
        await g.record_success(0.60, domain="hr_policy", provider="groq")

        decision = await g.precheck(0.01)

        assert decision == SpendDecision.BLOCK
    finally:
        await g.aclose()


@pytest.mark.anyio
async def test_record_failure_trips_after_threshold_and_precheck_still_allows(
    guard: SpendGuard,
) -> None:
    tripped = False
    for _ in range(3):
        tripped = await guard.record_failure(provider="groq")

    assert tripped is True
    assert await guard.is_provider_available(provider="groq") is False
    # precheck() itself is budget/velocity-scoped, not per-provider — a tripped
    # provider is a signal the caller (Plan 2c's domain code) checks separately
    # via is_provider_available() before choosing which provider to force.
    assert await guard.precheck(0.05) == SpendDecision.ALLOW


@pytest.mark.anyio
async def test_record_success_resets_provider_availability(guard: SpendGuard) -> None:
    for _ in range(3):
        await guard.record_failure(provider="groq")
    assert await guard.is_provider_available(provider="groq") is False

    await guard.record_success(0.01, domain="hr_policy", provider="groq")

    assert await guard.is_provider_available(provider="groq") is True


@pytest.mark.anyio
async def test_create_spend_guard_raises_without_dsn() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        await create_spend_guard(env={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_guard.py -v` (from `packages/spend_guard/`)
Expected: FAIL — `spend_guard.guard` doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Create `packages/spend_guard/src/spend_guard/guard.py`:

```python
from __future__ import annotations

import os
from enum import Enum

import asyncpg

from spend_guard import budget, circuit_breaker


class SpendDecision(str, Enum):
    ALLOW = "allow"
    DOWNGRADE_TO_LOCAL = "downgrade_to_local"
    BLOCK = "block"


class SpendGuard:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        daily_cap_usd: float,
        monthly_cap_usd: float,
        circuit_breaker_threshold: int,
        circuit_breaker_cooldown_seconds: int,
        velocity_threshold_usd_per_minute: float,
    ) -> None:
        self._pool = pool
        self._daily_cap_usd = daily_cap_usd
        self._monthly_cap_usd = monthly_cap_usd
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._circuit_breaker_cooldown_seconds = circuit_breaker_cooldown_seconds
        self._velocity_threshold_usd_per_minute = velocity_threshold_usd_per_minute

    async def precheck(
        self, estimated_cost_usd: float, *, has_local_fallback: bool = True
    ) -> SpendDecision:
        async with self._pool.acquire() as conn:
            if await circuit_breaker.is_global_breaker_tripped(
                conn, cooldown_seconds=self._circuit_breaker_cooldown_seconds
            ):
                return SpendDecision.BLOCK

            velocity = await circuit_breaker.get_spend_velocity(conn)
            if velocity >= self._velocity_threshold_usd_per_minute:
                await circuit_breaker.trip_global_breaker(conn)
                return SpendDecision.BLOCK

            status = await budget.get_budget_status(
                conn, daily_cap_usd=self._daily_cap_usd, monthly_cap_usd=self._monthly_cap_usd
            )
            projected_today = status.spent_today_usd + estimated_cost_usd
            projected_month = status.spent_this_month_usd + estimated_cost_usd
            if (
                projected_today > status.daily_cap_usd
                or projected_month > status.monthly_cap_usd
            ):
                return (
                    SpendDecision.DOWNGRADE_TO_LOCAL
                    if has_local_fallback
                    else SpendDecision.BLOCK
                )

        return SpendDecision.ALLOW

    async def record_success(self, cost_usd: float, *, domain: str, provider: str) -> None:
        async with self._pool.acquire() as conn:
            await budget.record_spend(conn, domain=domain, provider=provider, cost_usd=cost_usd)
            await circuit_breaker.record_provider_success(conn, provider=provider)

    async def record_failure(self, *, provider: str) -> bool:
        async with self._pool.acquire() as conn:
            status = await circuit_breaker.record_provider_failure(
                conn, provider=provider, threshold=self._circuit_breaker_threshold
            )
        return status.tripped

    async def is_provider_available(self, *, provider: str) -> bool:
        async with self._pool.acquire() as conn:
            return not await circuit_breaker.is_provider_tripped(
                conn, provider=provider, cooldown_seconds=self._circuit_breaker_cooldown_seconds
            )

    async def aclose(self) -> None:
        await self._pool.close()


async def create_spend_guard(
    dsn: str | None = None, *, env: dict[str, str] | None = None
) -> SpendGuard:
    source = env if env is not None else dict(os.environ)
    resolved_dsn = dsn if dsn is not None else source.get("DATABASE_URL", "")
    if not resolved_dsn:
        raise ValueError("DATABASE_URL is not configured")
    pool = await asyncpg.create_pool(resolved_dsn)
    return SpendGuard(
        pool,
        daily_cap_usd=float(source.get("SPEND_GUARD_DAILY_CAP_USD", "1.0")),
        monthly_cap_usd=float(source.get("SPEND_GUARD_MONTHLY_CAP_USD", "20.0")),
        circuit_breaker_threshold=int(source.get("SPEND_GUARD_CIRCUIT_BREAKER_THRESHOLD", "5")),
        circuit_breaker_cooldown_seconds=int(
            source.get("SPEND_GUARD_CIRCUIT_BREAKER_COOLDOWN_SECONDS", "300")
        ),
        velocity_threshold_usd_per_minute=float(
            source.get("SPEND_GUARD_VELOCITY_THRESHOLD_USD_PER_MINUTE", "0.50")
        ),
    )
```

Modify `packages/spend_guard/src/spend_guard/__init__.py` to re-export the public entrypoint:

```python
from spend_guard.guard import SpendDecision, SpendGuard, create_spend_guard

__all__ = ["SpendDecision", "SpendGuard", "create_spend_guard"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_guard.py -v`
Expected: all 7 PASS. Full package suite: `pytest -v` should show all tests across `test_schema_bootstrap.py`, `test_budget.py`, `test_circuit_breaker.py`, `test_guard.py` passing (1 + 3 + 5 + 7 = 16 total).

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/spend_guard/src/spend_guard/guard.py packages/spend_guard/src/spend_guard/__init__.py packages/spend_guard/tests/test_guard.py
git commit -m "feat(spend-guard): add SpendGuard facade (precheck, record_success/failure)"
```

---

### Task 7: CI wiring for `packages/spend_guard`

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:** none new — this wires Tasks 3-6's package into the existing CI pipeline, using a Postgres service container (GitHub Actions runs this natively — no Docker installation needed on the runner, unlike this local dev machine which has no Docker but does have a local Postgres binary).

> **Stop and confirm with the user before the branch-protection step below.** Updating required status checks on `main` is a visible, shared-repo-settings change — confirm before running it, per Global Constraints, exactly as Week 1's Task 6 and Week 2a's Task 9 did.

- [ ] **Step 1: Add the CI job**

Modify `.github/workflows/ci.yml`, adding a new job (place it near the `model-gateway` job for readability):

```yaml
  spend-guard:
    name: "Spend Guard (lint, type-check, test)"
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: spend_guard_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    defaults:
      run:
        working-directory: packages/spend_guard
    env:
      TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/spend_guard_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Ruff lint
        run: ruff check .
      - name: Black format check
        run: black --check .
      - name: mypy
        run: mypy src
      - name: pytest
        run: pytest -v
```

- [ ] **Step 2: Validate YAML syntax locally**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('OK: valid YAML')"
```
Expected: `OK: valid YAML`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint/type-check/test job for packages/spend_guard (with Postgres service)"
```

- [ ] **Step 4: (Controller-level, after this branch is pushed and has a passing CI run) Add the new check to branch protection**

Not part of the implementer's task — done by whoever is running subagent-driven-development, after this branch is pushed and a real "Spend Guard (lint, type-check, test)" check has passed on GitHub (confirm with the user first, per the note above this task):

```bash
gh api repos/{owner}/{repo}/branches/main/protection \
  --method PUT \
  -f required_status_checks.strict=true \
  -f 'required_status_checks.contexts[]=API (lint, type-check, test)' \
  -f 'required_status_checks.contexts[]=Web (build)' \
  -f 'required_status_checks.contexts[]=Model Gateway (lint, type-check, test)' \
  -f 'required_status_checks.contexts[]=Spend Guard (lint, type-check, test)' \
  -f enforce_admins=true \
  -f required_pull_request_reviews=null \
  -f restrictions=null
```
(As in prior weeks, if `gh api` with dotted `-f` keys for a nested array fails schema validation, write the JSON body to a file and use `--input` instead.)
Expected: response JSON lists all four contexts under `required_status_checks.contexts`.

---

## Plan 2b Exit Criteria

- [ ] `packages/model_gateway`'s `embed()` now returns cost/logging parity with `complete()`, and `complete()` supports `force_provider` for downgrade — both covered by new tests, full suite (39 tests) passing.
- [ ] `packages/spend_guard` has zero-tolerance-clean ruff/black/strict-mypy and a full passing test suite (16 tests) against a **real** local Postgres instance — no database mocking.
- [ ] Budget enforcement (daily/monthly caps, ALLOW/DOWNGRADE_TO_LOCAL/BLOCK decisions) and the circuit breaker (per-provider consecutive-failure trip/cooldown, global spend-velocity trip) are both demonstrated by tests, not just claimed.
- [ ] CI enforces this package the same way it enforces `apps/api`, `apps/web`, and `packages/model_gateway`.
- [ ] Nothing in this plan touches Postgres provisioning (Supabase), deployment, or any domain's actual HTTP endpoints — those are Plan 2c.
