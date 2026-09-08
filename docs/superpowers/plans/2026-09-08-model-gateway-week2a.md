# Model Gateway (Week 2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `packages/model_gateway` — a standalone, fully-tested multi-provider LLM/embedding inference service (8 LLM providers, 4 embedding providers, config-driven fallback chain, retry, cost estimation, prompt caching) that any domain can call. This plan does NOT wire it into a domain or add Spend Guard/Postgres — that's Plan 2b (`docs/superpowers/plans/<tbd>-spend-guard-hr-integration.md`), so this package is independently testable and mergeable on its own.

**Architecture:** Three adapter shapes cover all 8 LLM + 4 embedding provider configs: `OpenAICompatibleProvider` (OpenAI, Groq, Mistral, Cohere-compat, HuggingFace-router, Ollama — all speak the OpenAI chat-completions/embeddings wire format), `AnthropicProvider` (Messages API, with `cache_control` prompt caching), and `GeminiProvider` (generateContent/embedContent). A fourth, `HuggingFaceEmbeddingProvider`, covers HF's classic feature-extraction embeddings endpoint. `ModelGateway` orchestrates: resolve the configured fallback chain → for each provider, retry transient failures with backoff → on sustained failure, advance to the next provider → estimate cost from the pricing table → emit a structured log line. All provider calls go through an injectable `httpx.AsyncClient`, so every test uses `httpx.MockTransport` — zero real network calls, zero API keys needed to run the suite.

**Tech Stack:** Python 3.11+, httpx (async), PyYAML, pytest + anyio (async tests), ruff, black, mypy (strict).

**Spec:** `docs/superpowers/specs/2026-09-07-agentic-rag-platform-design.md` (§4 Model Gateway is this plan's primary source; §5 Spend Guard's cost-estimator dependency is why `pricing.py`'s interface matters beyond this plan; §9 Code Quality Standards for the strict-mypy-on-packages/ requirement and the mocked-test cost-safety rule).

## Global Constraints

- Python source targets `>=3.11` (matches Week 1's `apps/api`).
- Gate-tool versions are pinned to the exact versions already verified in `apps/api` for cross-package determinism (Week 1's final review found unpinned gate tools non-deterministic — applying that lesson proactively here): `pytest==9.1.1`, `ruff==0.16.6`, `black==26.5.1`, `mypy==2.3.1`.
- `packages/` gets **strict mypy** (`strict = true`), not the standard-mode config used for `apps/api/domains` — spec §9 draws this distinction explicitly.
- No secrets or `.env` files are ever committed. Provider API keys are read from environment variables only, at call time — never hardcoded, never logged.
- Tests must never make real network calls — every HTTP-touching test uses `httpx.MockTransport` via dependency-injected `httpx.AsyncClient`. This is what lets CI run without any provider API key (spec §9's cost-safety requirement).
- Retry (transient-blip handling, `max_retries` default 2, exponential backoff) happens *within* a single provider's call, before the fallback chain advances to the next provider — spec §4/§5 draws this distinction explicitly; the circuit breaker (sustained-failure handling, Postgres-persisted) is Spend Guard's job in Plan 2b, not this package's.
- Prompt caching (spec §4): Anthropic's `cache_control` on system blocks is implemented this plan. OpenAI's caching is automatic server-side — no request-shape change needed, just correctly surfacing `cached_tokens` from its usage response, which this plan does. Gemini's *explicit* context caching needs a large minimum token count impractical at this skeleton's scale — the usage/cost plumbing for it exists (`cached_input_tokens` field, `cachedContentTokenCount` parsing) but explicit cache creation is deliberately deferred until a domain's prompts are large enough to benefit from it (YAGNI, not silently skipped).
- Any step that modifies shared GitHub repo settings (branch protection) is a visible, external action — pause for explicit go-ahead before doing it, per the pattern established in Week 1.

---

### Task 1: Package skeleton, core types, and retry helper

**Files:**
- Create: `packages/model_gateway/pyproject.toml`
- Create: `packages/model_gateway/src/model_gateway/__init__.py`
- Create: `packages/model_gateway/src/model_gateway/types.py`
- Create: `packages/model_gateway/src/model_gateway/retry.py`
- Test: `packages/model_gateway/tests/conftest.py`
- Test: `packages/model_gateway/tests/test_retry.py`

**Interfaces:**
- Produces: `model_gateway.types.Role` (str Enum: SYSTEM/USER/ASSISTANT), `ChatMessage`, `Usage`, `CompletionResult`, `EmbeddingResult`, `ProviderError`, `ProviderAPIError` — every later task's provider adapters and the gateway import these.
- Produces: `model_gateway.retry.call_with_retry(fn, *, max_retries=2, base_delay_seconds=0.5) -> T` — Task 8's gateway wraps every provider call with this.

- [ ] **Step 1: Create the package config**

Create `packages/model_gateway/pyproject.toml`:

```toml
[project]
name = "model-gateway"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.28",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest==9.1.1",
    "anyio==4.15.1",
    "ruff==0.16.6",
    "black==26.5.1",
    "mypy==2.3.1",
    "types-PyYAML>=6.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/model_gateway"]

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

Create empty `packages/model_gateway/src/model_gateway/__init__.py`.

- [ ] **Step 2: Write the failing test for retry**

Create `packages/model_gateway/tests/conftest.py`:

```python
from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
```

Create `packages/model_gateway/tests/test_retry.py`:

```python
from __future__ import annotations

import pytest

from model_gateway.retry import call_with_retry


@pytest.mark.anyio
async def test_call_with_retry_returns_on_first_success() -> None:
    calls = {"count": 0}

    async def fn() -> str:
        calls["count"] += 1
        return "ok"

    result = await call_with_retry(fn, max_retries=2, base_delay_seconds=0.0)
    assert result == "ok"
    assert calls["count"] == 1


@pytest.mark.anyio
async def test_call_with_retry_succeeds_after_transient_failures() -> None:
    calls = {"count": 0}

    async def fn() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("transient")
        return "ok"

    result = await call_with_retry(fn, max_retries=2, base_delay_seconds=0.0)
    assert result == "ok"
    assert calls["count"] == 3


@pytest.mark.anyio
async def test_call_with_retry_raises_after_exhausting_retries() -> None:
    calls = {"count": 0}

    async def fn() -> str:
        calls["count"] += 1
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError, match="permanent"):
        await call_with_retry(fn, max_retries=2, base_delay_seconds=0.0)
    assert calls["count"] == 3
```

- [ ] **Step 3: Install and run test to verify it fails**

Run:
```bash
cd packages/model_gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```
Expected: FAIL / collection error — `model_gateway.retry` does not exist yet.

- [ ] **Step 4: Write types.py and retry.py**

Create `packages/model_gateway/src/model_gateway/types.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    usage: Usage
    latency_ms: float


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model: str
    usage: Usage
    latency_ms: float


class ProviderError(Exception):
    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class ProviderAPIError(ProviderError):
    def __init__(self, provider: str, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(provider, f"HTTP {status_code}: {message}")
```

Create `packages/model_gateway/src/model_gateway/retry.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def call_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 2,
    base_delay_seconds: float = 0.5,
) -> T:
    attempt = 0
    while True:
        try:
            return await fn()
        except Exception:
            if attempt >= max_retries:
                raise
            await asyncio.sleep(base_delay_seconds * (2**attempt))
            attempt += 1
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest -v`
Expected: all 3 tests PASS.

- [ ] **Step 6: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: all three clean.

- [ ] **Step 7: Commit**

```bash
git add packages/model_gateway/pyproject.toml packages/model_gateway/src packages/model_gateway/tests
git commit -m "feat(model-gateway): add package skeleton, core types, and retry helper"
```

---

### Task 2: Cost estimator and pricing table

**Files:**
- Create: `packages/model_gateway/src/model_gateway/pricing.yaml`
- Create: `packages/model_gateway/src/model_gateway/pricing.py`
- Test: `packages/model_gateway/tests/test_pricing.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `model_gateway.pricing.estimate_cost(*, provider: str, model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> float` — Task 8's gateway calls this after every successful completion.

- [ ] **Step 1: Write the failing test**

Create `packages/model_gateway/tests/test_pricing.py`:

```python
from __future__ import annotations

from model_gateway.pricing import estimate_cost


def test_estimate_cost_known_model() -> None:
    cost = estimate_cost(
        provider="groq",
        model="llama-3.3-70b-versatile",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert cost == 0.59 + 0.79


def test_estimate_cost_prices_cached_tokens_at_cached_rate() -> None:
    cost = estimate_cost(
        provider="anthropic",
        model="claude-3-5-haiku-latest",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_input_tokens=1_000_000,
    )
    assert cost == 0.08


def test_estimate_cost_unknown_model_returns_zero() -> None:
    cost = estimate_cost(provider="unknown", model="unknown", input_tokens=100, output_tokens=100)
    assert cost == 0.0


def test_estimate_cost_free_local_provider() -> None:
    cost = estimate_cost(
        provider="ollama", model="llama3.2", input_tokens=1_000_000, output_tokens=1_000_000
    )
    assert cost == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -v`
Expected: FAIL — `model_gateway.pricing` does not exist yet.

- [ ] **Step 3: Write the pricing table and estimator**

Create `packages/model_gateway/src/model_gateway/pricing.yaml`:

```yaml
# Illustrative per-1M-token USD pricing. Manually reviewed/updated — spec §4
# treats this as a non-goal to auto-sync from a live pricing API.
# An (provider, model) pair missing here estimates as $0 rather than
# raising, so a stale/missing price entry degrades to "untracked cost"
# instead of blocking a call.
groq:
  llama-3.3-70b-versatile:
    input_per_million: 0.59
    output_per_million: 0.79
    cached_input_per_million: 0.59
openai:
  gpt-4o-mini:
    input_per_million: 0.15
    output_per_million: 0.60
    cached_input_per_million: 0.075
  text-embedding-3-small:
    input_per_million: 0.02
    output_per_million: 0.0
    cached_input_per_million: 0.02
anthropic:
  claude-3-5-haiku-latest:
    input_per_million: 0.80
    output_per_million: 4.00
    cached_input_per_million: 0.08
gemini:
  gemini-2.0-flash:
    input_per_million: 0.10
    output_per_million: 0.40
    cached_input_per_million: 0.025
  text-embedding-004:
    input_per_million: 0.0
    output_per_million: 0.0
    cached_input_per_million: 0.0
mistral:
  mistral-small-latest:
    input_per_million: 0.20
    output_per_million: 0.60
    cached_input_per_million: 0.20
cohere:
  command-r:
    input_per_million: 0.15
    output_per_million: 0.60
    cached_input_per_million: 0.15
huggingface:
  meta-llama/Llama-3.1-8B-Instruct:
    input_per_million: 0.0
    output_per_million: 0.0
    cached_input_per_million: 0.0
  BAAI/bge-small-en-v1.5:
    input_per_million: 0.0
    output_per_million: 0.0
    cached_input_per_million: 0.0
ollama:
  llama3.2:
    input_per_million: 0.0
    output_per_million: 0.0
    cached_input_per_million: 0.0
  nomic-embed-text:
    input_per_million: 0.0
    output_per_million: 0.0
    cached_input_per_million: 0.0
```

Create `packages/model_gateway/src/model_gateway/pricing.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import yaml

_PRICING_PATH = Path(__file__).parent / "pricing.yaml"


class ModelPrice(TypedDict):
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float


def _load_pricing_table(path: Path = _PRICING_PATH) -> dict[str, dict[str, ModelPrice]]:
    with path.open() as f:
        raw = yaml.safe_load(f)
    return raw or {}


_PRICING_TABLE = _load_pricing_table()


def estimate_cost(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    price = _PRICING_TABLE.get(provider, {}).get(model)
    if price is None:
        return 0.0
    fresh_input_tokens = max(input_tokens - cached_input_tokens, 0)
    return (
        fresh_input_tokens * price["input_per_million"] / 1_000_000
        + cached_input_tokens * price["cached_input_per_million"] / 1_000_000
        + output_tokens * price["output_per_million"] / 1_000_000
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -v`
Expected: all tests PASS (previous 3 + 4 new = 7 total).

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean. (If mypy complains about `yaml.safe_load`'s return type, confirm `types-PyYAML` installed via Task 1's dev deps — it should already be present.)

- [ ] **Step 6: Commit**

```bash
git add packages/model_gateway/src/model_gateway/pricing.yaml packages/model_gateway/src/model_gateway/pricing.py packages/model_gateway/tests/test_pricing.py
git commit -m "feat(model-gateway): add cost estimator and pricing table"
```

---

### Task 3: Provider protocol and the OpenAI-compatible adapter

**Files:**
- Create: `packages/model_gateway/src/model_gateway/providers/__init__.py`
- Create: `packages/model_gateway/src/model_gateway/providers/base.py`
- Create: `packages/model_gateway/src/model_gateway/providers/openai_compatible.py`
- Test: `packages/model_gateway/tests/test_providers_openai_compatible.py`

**Interfaces:**
- Consumes: `model_gateway.types.{ChatMessage, CompletionResult, EmbeddingResult, ProviderAPIError, Role, Usage}` (Task 1).
- Produces: `model_gateway.providers.base.ChatProvider` / `EmbeddingProvider` (Protocols) — every provider adapter in this plan structurally satisfies one or both; Task 8's gateway type-hints against these.
- Produces: `model_gateway.providers.openai_compatible.OpenAICompatibleProvider(provider_name, base_url, api_key, timeout_seconds=30.0, client=None)` with async `complete(...)` and `embed(...)` — covers OpenAI, Groq, Mistral, Cohere (compat endpoint), HuggingFace (router), and Ollama (local) by configuration alone (Task 7 wires the actual base URLs/keys).

- [ ] **Step 1: Write the failing tests**

Create `packages/model_gateway/src/model_gateway/providers/__init__.py` (empty).

Create `packages/model_gateway/tests/test_providers_openai_compatible.py`:

```python
from __future__ import annotations

import httpx
import pytest

from model_gateway.providers.openai_compatible import OpenAICompatibleProvider
from model_gateway.types import ChatMessage, ProviderAPIError, Role


@pytest.mark.anyio
async def test_complete_returns_parsed_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.complete(
        [ChatMessage(role=Role.USER, content="hi")], model="llama-3.3-70b-versatile"
    )
    assert result.text == "hello"
    assert result.provider == "groq"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 2
    assert result.usage.cached_input_tokens == 0


@pytest.mark.anyio
async def test_complete_surfaces_cached_tokens_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                "usage": {
                    "prompt_tokens": 500,
                    "completion_tokens": 5,
                    "prompt_tokens_details": {"cached_tokens": 400},
                },
            },
        )

    provider = OpenAICompatibleProvider(
        provider_name="openai",
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.complete([ChatMessage(role=Role.USER, content="hi")], model="gpt-4o-mini")
    assert result.usage.cached_input_tokens == 400


@pytest.mark.anyio
async def test_complete_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    provider = OpenAICompatibleProvider(
        provider_name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderAPIError):
        await provider.complete([ChatMessage(role=Role.USER, content="hi")], model="m")


@pytest.mark.anyio
async def test_embed_returns_vectors_in_index_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/embeddings"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.2, 0.3], "index": 1},
                    {"embedding": [0.1, 0.1], "index": 0},
                ],
                "usage": {"prompt_tokens": 5},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_name="ollama",
        base_url="http://localhost:11434/v1",
        api_key="",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.embed(["a", "b"], model="nomic-embed-text")
    assert result.vectors == [[0.1, 0.1], [0.2, 0.3]]


@pytest.mark.anyio
async def test_headers_omit_authorization_when_no_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    provider = OpenAICompatibleProvider(
        provider_name="ollama",
        base_url="http://localhost:11434/v1",
        api_key="",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await provider.complete([ChatMessage(role=Role.USER, content="hi")], model="llama3.2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -v`
Expected: FAIL — `model_gateway.providers` module does not exist yet.

- [ ] **Step 3: Write the protocol and adapter**

Create `packages/model_gateway/src/model_gateway/providers/base.py`:

```python
from __future__ import annotations

from typing import Protocol

from model_gateway.types import ChatMessage, CompletionResult, EmbeddingResult


class ChatProvider(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> CompletionResult: ...


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str], *, model: str) -> EmbeddingResult: ...
```

Create `packages/model_gateway/src/model_gateway/providers/openai_compatible.py`:

```python
from __future__ import annotations

import time

import httpx

from model_gateway.types import (
    ChatMessage,
    CompletionResult,
    EmbeddingResult,
    ProviderAPIError,
    Usage,
)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider_name = provider_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._client = client or httpx.AsyncClient()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> CompletionResult:
        start = time.monotonic()
        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": model,
                "messages": [{"role": m.role.value, "content": m.content} for m in messages],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self._timeout,
        )
        latency_ms = (time.monotonic() - start) * 1000
        if response.status_code >= 400:
            raise ProviderAPIError(self.provider_name, response.status_code, response.text)
        body = response.json()
        choice = body["choices"][0]["message"]
        usage_body = body.get("usage", {})
        cached = usage_body.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        return CompletionResult(
            text=choice["content"],
            provider=self.provider_name,
            model=model,
            usage=Usage(
                input_tokens=usage_body.get("prompt_tokens", 0),
                output_tokens=usage_body.get("completion_tokens", 0),
                cached_input_tokens=cached,
            ),
            latency_ms=latency_ms,
        )

    async def embed(self, texts: list[str], *, model: str) -> EmbeddingResult:
        start = time.monotonic()
        response = await self._client.post(
            f"{self._base_url}/embeddings",
            headers=self._headers(),
            json={"model": model, "input": texts},
            timeout=self._timeout,
        )
        latency_ms = (time.monotonic() - start) * 1000
        if response.status_code >= 400:
            raise ProviderAPIError(self.provider_name, response.status_code, response.text)
        body = response.json()
        ordered = sorted(body["data"], key=lambda item: item["index"])
        usage_body = body.get("usage", {})
        return EmbeddingResult(
            vectors=[item["embedding"] for item in ordered],
            provider=self.provider_name,
            model=model,
            usage=Usage(input_tokens=usage_body.get("prompt_tokens", 0), output_tokens=0),
            latency_ms=latency_ms,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -v`
Expected: all tests PASS (previous 7 + 5 new = 12 total).

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/model_gateway/src/model_gateway/providers packages/model_gateway/tests/test_providers_openai_compatible.py
git commit -m "feat(model-gateway): add provider protocol and OpenAI-compatible adapter"
```

---

### Task 4: Anthropic adapter with prompt caching

**Files:**
- Create: `packages/model_gateway/src/model_gateway/providers/anthropic.py`
- Test: `packages/model_gateway/tests/test_providers_anthropic.py`

**Interfaces:**
- Consumes: `model_gateway.types.{ChatMessage, CompletionResult, ProviderAPIError, Role, Usage}` (Task 1), structurally satisfies `ChatProvider` (Task 3).
- Produces: `model_gateway.providers.anthropic.AnthropicProvider(api_key, base_url="https://api.anthropic.com/v1", timeout_seconds=30.0, client=None)` with async `complete(...)`.

- [ ] **Step 1: Write the failing tests**

Create `packages/model_gateway/tests/test_providers_anthropic.py`:

```python
from __future__ import annotations

import json

import httpx
import pytest

from model_gateway.providers.anthropic import AnthropicProvider
from model_gateway.types import ChatMessage, ProviderAPIError, Role


@pytest.mark.anyio
async def test_complete_sends_system_as_cached_block_and_parses_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/messages"
        assert request.headers["x-api-key"] == "test-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "hello"}],
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 30,
                },
            },
        )

    provider = AnthropicProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.complete(
        [
            ChatMessage(role=Role.SYSTEM, content="You are an HR assistant."),
            ChatMessage(role=Role.USER, content="What is the leave policy?"),
        ],
        model="claude-3-5-haiku-latest",
    )

    body = captured["body"]
    assert isinstance(body, dict)
    system_blocks = body["system"]
    assert system_blocks == [
        {
            "type": "text",
            "text": "You are an HR assistant.",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert body["messages"] == [{"role": "user", "content": "What is the leave policy?"}]

    assert result.text == "hello"
    assert result.provider == "anthropic"
    assert result.usage.input_tokens == 50
    assert result.usage.output_tokens == 5
    assert result.usage.cached_input_tokens == 30


@pytest.mark.anyio
async def test_complete_concatenates_multiple_text_blocks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    provider = AnthropicProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.complete([ChatMessage(role=Role.USER, content="hi")], model="m")
    assert result.text == "hello world"


@pytest.mark.anyio
async def test_complete_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(529, text="overloaded")

    provider = AnthropicProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderAPIError):
        await provider.complete([ChatMessage(role=Role.USER, content="hi")], model="m")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -v`
Expected: FAIL — `model_gateway.providers.anthropic` does not exist yet.

- [ ] **Step 3: Write the adapter**

Create `packages/model_gateway/src/model_gateway/providers/anthropic.py`:

```python
from __future__ import annotations

import time

import httpx

from model_gateway.types import ChatMessage, CompletionResult, ProviderAPIError, Role, Usage

_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider_name = "anthropic"
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client or httpx.AsyncClient()

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> CompletionResult:
        system_blocks = [
            {"type": "text", "text": m.content, "cache_control": {"type": "ephemeral"}}
            for m in messages
            if m.role == Role.SYSTEM
        ]
        turn_messages = [
            {"role": m.role.value, "content": m.content} for m in messages if m.role != Role.SYSTEM
        ]

        start = time.monotonic()
        response = await self._client.post(
            f"{self._base_url}/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_blocks,
                "messages": turn_messages,
            },
            timeout=self._timeout,
        )
        latency_ms = (time.monotonic() - start) * 1000
        if response.status_code >= 400:
            raise ProviderAPIError(self.provider_name, response.status_code, response.text)
        body = response.json()
        text = "".join(block["text"] for block in body["content"] if block["type"] == "text")
        usage_body = body.get("usage", {})
        return CompletionResult(
            text=text,
            provider=self.provider_name,
            model=model,
            usage=Usage(
                input_tokens=usage_body.get("input_tokens", 0),
                output_tokens=usage_body.get("output_tokens", 0),
                cached_input_tokens=usage_body.get("cache_read_input_tokens", 0),
            ),
            latency_ms=latency_ms,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -v`
Expected: all tests PASS (previous 12 + 3 new = 15 total).

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/model_gateway/src/model_gateway/providers/anthropic.py packages/model_gateway/tests/test_providers_anthropic.py
git commit -m "feat(model-gateway): add Anthropic adapter with prompt caching"
```

---

### Task 5: Gemini adapter (chat + embeddings)

**Files:**
- Create: `packages/model_gateway/src/model_gateway/providers/gemini.py`
- Test: `packages/model_gateway/tests/test_providers_gemini.py`

**Interfaces:**
- Consumes: `model_gateway.types.{ChatMessage, CompletionResult, EmbeddingResult, ProviderAPIError, Role, Usage}` (Task 1), structurally satisfies both `ChatProvider` and `EmbeddingProvider` (Task 3).
- Produces: `model_gateway.providers.gemini.GeminiProvider(api_key, base_url="https://generativelanguage.googleapis.com/v1beta", timeout_seconds=30.0, client=None)` with async `complete(...)` and `embed(...)`.

- [ ] **Step 1: Write the failing tests**

Create `packages/model_gateway/tests/test_providers_gemini.py`:

```python
from __future__ import annotations

import json

import httpx
import pytest

from model_gateway.providers.gemini import GeminiProvider
from model_gateway.types import ChatMessage, ProviderAPIError, Role


@pytest.mark.anyio
async def test_complete_sends_system_instruction_and_parses_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/models/gemini-2.0-flash:generateContent" in str(request.url)
        assert request.url.params["key"] == "test-key"
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "hello"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 20,
                    "candidatesTokenCount": 3,
                    "cachedContentTokenCount": 0,
                },
            },
        )

    provider = GeminiProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.complete(
        [
            ChatMessage(role=Role.SYSTEM, content="You are an HR assistant."),
            ChatMessage(role=Role.USER, content="What is the leave policy?"),
        ],
        model="gemini-2.0-flash",
    )

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["systemInstruction"] == {"parts": [{"text": "You are an HR assistant."}]}
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "What is the leave policy?"}]}
    ]

    assert result.text == "hello"
    assert result.provider == "gemini"
    assert result.usage.input_tokens == 20
    assert result.usage.output_tokens == 3


@pytest.mark.anyio
async def test_complete_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    provider = GeminiProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderAPIError):
        await provider.complete([ChatMessage(role=Role.USER, content="hi")], model="m")


@pytest.mark.anyio
async def test_embed_returns_one_vector_per_text() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        assert "embedContent" in str(request.url)
        return httpx.Response(200, json={"embedding": {"values": [0.1, 0.2]}})

    provider = GeminiProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.embed(["a", "b"], model="text-embedding-004")
    assert result.vectors == [[0.1, 0.2], [0.1, 0.2]]
    assert calls["count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -v`
Expected: FAIL — `model_gateway.providers.gemini` does not exist yet.

- [ ] **Step 3: Write the adapter**

Create `packages/model_gateway/src/model_gateway/providers/gemini.py`:

```python
from __future__ import annotations

import time

import httpx

from model_gateway.types import (
    ChatMessage,
    CompletionResult,
    EmbeddingResult,
    ProviderAPIError,
    Role,
    Usage,
)


class GeminiProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider_name = "gemini"
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client or httpx.AsyncClient()

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> CompletionResult:
        system_text = "\n".join(m.content for m in messages if m.role == Role.SYSTEM)
        contents = [
            {
                "role": "model" if m.role == Role.ASSISTANT else "user",
                "parts": [{"text": m.content}],
            }
            for m in messages
            if m.role != Role.SYSTEM
        ]
        payload: dict[str, object] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        start = time.monotonic()
        response = await self._client.post(
            f"{self._base_url}/models/{model}:generateContent",
            params={"key": self._api_key},
            json=payload,
            timeout=self._timeout,
        )
        latency_ms = (time.monotonic() - start) * 1000
        if response.status_code >= 400:
            raise ProviderAPIError(self.provider_name, response.status_code, response.text)
        body = response.json()
        parts = body["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts)
        usage_body = body.get("usageMetadata", {})
        return CompletionResult(
            text=text,
            provider=self.provider_name,
            model=model,
            usage=Usage(
                input_tokens=usage_body.get("promptTokenCount", 0),
                output_tokens=usage_body.get("candidatesTokenCount", 0),
                cached_input_tokens=usage_body.get("cachedContentTokenCount", 0),
            ),
            latency_ms=latency_ms,
        )

    async def embed(self, texts: list[str], *, model: str) -> EmbeddingResult:
        start = time.monotonic()
        vectors: list[list[float]] = []
        for text in texts:
            response = await self._client.post(
                f"{self._base_url}/models/{model}:embedContent",
                params={"key": self._api_key},
                json={"content": {"parts": [{"text": text}]}},
                timeout=self._timeout,
            )
            if response.status_code >= 400:
                raise ProviderAPIError(self.provider_name, response.status_code, response.text)
            vectors.append(response.json()["embedding"]["values"])
        latency_ms = (time.monotonic() - start) * 1000
        return EmbeddingResult(
            vectors=vectors,
            provider=self.provider_name,
            model=model,
            usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=latency_ms,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -v`
Expected: all tests PASS (previous 15 + 3 new = 18 total).

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/model_gateway/src/model_gateway/providers/gemini.py packages/model_gateway/tests/test_providers_gemini.py
git commit -m "feat(model-gateway): add Gemini adapter for chat and embeddings"
```

---

### Task 6: HuggingFace embeddings adapter

**Files:**
- Create: `packages/model_gateway/src/model_gateway/providers/huggingface_embed.py`
- Test: `packages/model_gateway/tests/test_providers_huggingface_embed.py`

**Interfaces:**
- Consumes: `model_gateway.types.{EmbeddingResult, ProviderAPIError, Usage}` (Task 1), structurally satisfies `EmbeddingProvider` (Task 3).
- Produces: `model_gateway.providers.huggingface_embed.HuggingFaceEmbeddingProvider(api_key, base_url="https://api-inference.huggingface.co/models", timeout_seconds=30.0, client=None)` with async `embed(...)`.

- [ ] **Step 1: Write the failing tests**

Create `packages/model_gateway/tests/test_providers_huggingface_embed.py`:

```python
from __future__ import annotations

import httpx
import pytest

from model_gateway.providers.huggingface_embed import HuggingFaceEmbeddingProvider
from model_gateway.types import ProviderAPIError


@pytest.mark.anyio
async def test_embed_returns_one_vector_per_input() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/models/BAAI/bge-small-en-v1.5"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=[[0.1, 0.2], [0.3, 0.4]])

    provider = HuggingFaceEmbeddingProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.embed(["a", "b"], model="BAAI/bge-small-en-v1.5")
    assert result.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert result.provider == "huggingface"


@pytest.mark.anyio
async def test_embed_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="model loading")

    provider = HuggingFaceEmbeddingProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderAPIError):
        await provider.embed(["a"], model="BAAI/bge-small-en-v1.5")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -v`
Expected: FAIL — `model_gateway.providers.huggingface_embed` does not exist yet.

- [ ] **Step 3: Write the adapter**

Create `packages/model_gateway/src/model_gateway/providers/huggingface_embed.py`:

```python
from __future__ import annotations

import time

import httpx

from model_gateway.types import EmbeddingResult, ProviderAPIError, Usage


class HuggingFaceEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api-inference.huggingface.co/models",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider_name = "huggingface"
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client or httpx.AsyncClient()

    async def embed(self, texts: list[str], *, model: str) -> EmbeddingResult:
        start = time.monotonic()
        response = await self._client.post(
            f"{self._base_url}/{model}",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"inputs": texts},
            timeout=self._timeout,
        )
        latency_ms = (time.monotonic() - start) * 1000
        if response.status_code >= 400:
            raise ProviderAPIError(self.provider_name, response.status_code, response.text)
        return EmbeddingResult(
            vectors=response.json(),
            provider=self.provider_name,
            model=model,
            usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=latency_ms,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -v`
Expected: all tests PASS (previous 18 + 2 new = 20 total).

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/model_gateway/src/model_gateway/providers/huggingface_embed.py packages/model_gateway/tests/test_providers_huggingface_embed.py
git commit -m "feat(model-gateway): add HuggingFace embeddings adapter"
```

---

### Task 7: Env-driven settings and provider registry

**Files:**
- Create: `packages/model_gateway/src/model_gateway/settings.py`
- Test: `packages/model_gateway/tests/test_settings.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure config/env parsing).
- Produces: `model_gateway.settings.ProviderConfig(name, base_url, api_key, model)`, `model_gateway.settings.GatewaySettings` (with `.llm_fallback_chain() -> list[str]` and `.embed_fallback_chain() -> list[str]`), and `model_gateway.settings.load_settings(env: dict[str, str] | None = None) -> GatewaySettings` — Task 8's gateway is built from this.

- [ ] **Step 1: Write the failing tests**

Create `packages/model_gateway/tests/test_settings.py`:

```python
from __future__ import annotations

from model_gateway.settings import load_settings


def test_load_settings_defaults() -> None:
    settings = load_settings(env={})
    assert settings.llm_primary == "groq"
    assert settings.llm_local == "ollama"
    assert settings.embed_primary == "ollama"
    assert "groq" in settings.llm_providers
    assert "anthropic" in settings.llm_providers
    assert "gemini" in settings.embed_providers
    assert "huggingface" in settings.embed_providers


def test_load_settings_reads_env_overrides() -> None:
    settings = load_settings(
        env={
            "LLM_PROVIDER": "openai",
            "LLM_PROVIDER_SECONDARY": "anthropic",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_MODEL": "gpt-4o",
        }
    )
    assert settings.llm_primary == "openai"
    assert settings.llm_secondary == "anthropic"
    assert settings.llm_providers["openai"].api_key == "sk-test"
    assert settings.llm_providers["openai"].model == "gpt-4o"


def test_llm_fallback_chain_dedupes_and_skips_unconfigured() -> None:
    settings = load_settings(
        env={"LLM_PROVIDER": "groq", "LLM_PROVIDER_SECONDARY": "groq", "LLM_PROVIDER_LOCAL": "ollama"}
    )
    assert settings.llm_fallback_chain() == ["groq", "ollama"]


def test_llm_fallback_chain_skips_local_when_equal_to_primary() -> None:
    settings = load_settings(env={"LLM_PROVIDER": "ollama", "LLM_PROVIDER_LOCAL": "ollama"})
    assert settings.llm_fallback_chain() == ["ollama"]


def test_embed_fallback_chain_empty_secondary_is_skipped() -> None:
    settings = load_settings(env={"EMBED_PROVIDER": "ollama", "EMBED_PROVIDER_SECONDARY": ""})
    assert settings.embed_fallback_chain() == ["ollama"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -v`
Expected: FAIL — `model_gateway.settings` does not exist yet.

- [ ] **Step 3: Write settings.py**

Create `packages/model_gateway/src/model_gateway/settings.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class GatewaySettings:
    llm_primary: str
    llm_secondary: str
    llm_local: str
    embed_primary: str
    embed_secondary: str
    timeout_seconds: float
    max_retries: int
    retry_base_delay_seconds: float = 0.5
    llm_providers: dict[str, ProviderConfig] = field(default_factory=dict)
    embed_providers: dict[str, ProviderConfig] = field(default_factory=dict)

    def llm_fallback_chain(self) -> list[str]:
        chain = [self.llm_primary]
        for name in (self.llm_secondary, self.llm_local):
            if name and name not in chain:
                chain.append(name)
        return [name for name in chain if name in self.llm_providers]

    def embed_fallback_chain(self) -> list[str]:
        chain = [self.embed_primary]
        if self.embed_secondary and self.embed_secondary not in chain:
            chain.append(self.embed_secondary)
        return [name for name in chain if name in self.embed_providers]


def load_settings(env: dict[str, str] | None = None) -> GatewaySettings:
    source = env if env is not None else dict(os.environ)

    def get(key: str, default: str = "") -> str:
        return source.get(key, default)

    ollama_base = get("OLLAMA_BASE_URL", "http://localhost:11434")

    llm_providers = {
        "groq": ProviderConfig(
            "groq",
            "https://api.groq.com/openai/v1",
            get("GROQ_API_KEY"),
            get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        ),
        "openai": ProviderConfig(
            "openai",
            "https://api.openai.com/v1",
            get("OPENAI_API_KEY"),
            get("OPENAI_MODEL", "gpt-4o-mini"),
        ),
        "mistral": ProviderConfig(
            "mistral",
            "https://api.mistral.ai/v1",
            get("MISTRAL_API_KEY"),
            get("MISTRAL_MODEL", "mistral-small-latest"),
        ),
        "cohere": ProviderConfig(
            "cohere",
            "https://api.cohere.com/compatibility/v1",
            get("COHERE_API_KEY"),
            get("COHERE_MODEL", "command-r"),
        ),
        "huggingface": ProviderConfig(
            "huggingface",
            "https://router.huggingface.co/v1",
            get("HUGGINGFACE_API_KEY"),
            get("HUGGINGFACE_MODEL", "meta-llama/Llama-3.1-8B-Instruct"),
        ),
        "ollama": ProviderConfig(
            "ollama", f"{ollama_base}/v1", "", get("OLLAMA_LLM_MODEL", "llama3.2")
        ),
        "anthropic": ProviderConfig(
            "anthropic",
            "https://api.anthropic.com/v1",
            get("ANTHROPIC_API_KEY"),
            get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
        ),
        "gemini": ProviderConfig(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            get("GEMINI_API_KEY"),
            get("GEMINI_MODEL", "gemini-2.0-flash"),
        ),
    }
    embed_providers = {
        "ollama": ProviderConfig(
            "ollama", f"{ollama_base}/v1", "", get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        ),
        "gemini": ProviderConfig(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            get("GEMINI_API_KEY"),
            get("GEMINI_EMBED_MODEL", "text-embedding-004"),
        ),
        "huggingface": ProviderConfig(
            "huggingface",
            "https://api-inference.huggingface.co/models",
            get("HUGGINGFACE_API_KEY"),
            get("HUGGINGFACE_EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
        ),
        "openai": ProviderConfig(
            "openai",
            "https://api.openai.com/v1",
            get("OPENAI_API_KEY"),
            get("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        ),
    }

    return GatewaySettings(
        llm_primary=get("LLM_PROVIDER", "groq"),
        llm_secondary=get("LLM_PROVIDER_SECONDARY", ""),
        llm_local=get("LLM_PROVIDER_LOCAL", "ollama"),
        embed_primary=get("EMBED_PROVIDER", "ollama"),
        embed_secondary=get("EMBED_PROVIDER_SECONDARY", ""),
        timeout_seconds=float(get("MODEL_GATEWAY_TIMEOUT_SECONDS", "30")),
        max_retries=int(get("MODEL_GATEWAY_MAX_RETRIES", "2")),
        retry_base_delay_seconds=float(get("MODEL_GATEWAY_RETRY_BASE_DELAY_SECONDS", "0.5")),
        llm_providers=llm_providers,
        embed_providers=embed_providers,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -v`
Expected: all tests PASS (previous 20 + 5 new = 25 total).

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/model_gateway/src/model_gateway/settings.py packages/model_gateway/tests/test_settings.py
git commit -m "feat(model-gateway): add env-driven settings and provider registry"
```

---

### Task 8: ModelGateway orchestrator (fallback, retry, cost, logging)

**Files:**
- Create: `packages/model_gateway/src/model_gateway/gateway.py`
- Modify: `packages/model_gateway/src/model_gateway/__init__.py`
- Test: `packages/model_gateway/tests/test_gateway.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7 (`types`, `retry.call_with_retry`, `pricing.estimate_cost`, all 4 provider adapters via `providers.base` Protocols, `settings.{GatewaySettings, ProviderConfig, load_settings}`).
- Produces: `model_gateway.gateway.ModelGateway(settings=None, *, client=None)` with async `complete(messages, *, temperature=0.1, max_tokens=1024) -> ChatOutcome` and async `embed(texts) -> EmbeddingResult`; `ChatOutcome(result: CompletionResult, estimated_cost_usd: float, attempted_providers: list[str])`. Re-exported from `model_gateway.__init__` as the package's main entrypoint — this is what Plan 2b's Spend Guard middleware and the `hr_policy` domain will import.

- [ ] **Step 1: Write the failing tests**

Create `packages/model_gateway/tests/test_gateway.py`:

```python
from __future__ import annotations

import httpx
import pytest

from model_gateway.gateway import ModelGateway
from model_gateway.settings import GatewaySettings, ProviderConfig
from model_gateway.types import ChatMessage, ProviderError, Role

_SUCCESS_BODY = {
    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}


def _settings_with(
    llm_providers: dict[str, ProviderConfig],
    *,
    secondary: str = "",
    local: str = "",
    max_retries: int = 0,
) -> GatewaySettings:
    return GatewaySettings(
        llm_primary="primary",
        llm_secondary=secondary,
        llm_local=local,
        embed_primary="",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=max_retries,
        retry_base_delay_seconds=0.001,
        llm_providers=llm_providers,
        embed_providers={},
    )


@pytest.mark.anyio
async def test_complete_returns_result_and_cost_from_primary() -> None:
    # Uses the real "groq" provider name (not a "primary" placeholder) so the
    # cost estimate exercises a real pricing.yaml entry, not just a $0 miss.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_SUCCESS_BODY)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {
        "groq": ProviderConfig("groq", "https://primary.example/v1", "k", "llama-3.3-70b-versatile"),
    }
    settings = GatewaySettings(
        llm_primary="groq",
        llm_secondary="",
        llm_local="",
        embed_primary="",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        retry_base_delay_seconds=0.001,
        llm_providers=providers,
        embed_providers={},
    )
    gateway = ModelGateway(settings, client=client)

    outcome = await gateway.complete([ChatMessage(role=Role.USER, content="hi")])

    assert outcome.result.text == "ok"
    assert outcome.attempted_providers == ["groq"]
    assert outcome.estimated_cost_usd == pytest.approx((0.59 + 0.79) / 1_000_000)


@pytest.mark.anyio
async def test_complete_falls_back_to_secondary_on_primary_failure() -> None:
    call_count = {"primary": 0, "secondary": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "primary" in str(request.url):
            call_count["primary"] += 1
            return httpx.Response(500, text="boom")
        call_count["secondary"] += 1
        return httpx.Response(200, json=_SUCCESS_BODY)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {
        "primary": ProviderConfig("primary", "https://primary.example/v1", "k", "m"),
        "secondary": ProviderConfig("secondary", "https://secondary.example/v1", "k", "m"),
    }
    gateway = ModelGateway(_settings_with(providers, secondary="secondary"), client=client)

    outcome = await gateway.complete([ChatMessage(role=Role.USER, content="hi")])

    assert outcome.result.text == "ok"
    assert outcome.attempted_providers == ["primary", "secondary"]
    assert call_count["primary"] == 1
    assert call_count["secondary"] == 1


@pytest.mark.anyio
async def test_complete_retries_before_falling_back() -> None:
    attempts = {"primary": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["primary"] += 1
        if attempts["primary"] < 2:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_SUCCESS_BODY)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {"primary": ProviderConfig("primary", "https://primary.example/v1", "k", "m")}
    gateway = ModelGateway(_settings_with(providers, max_retries=1), client=client)

    outcome = await gateway.complete([ChatMessage(role=Role.USER, content="hi")])

    assert outcome.result.text == "ok"
    assert attempts["primary"] == 2


@pytest.mark.anyio
async def test_complete_raises_when_all_providers_fail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {"primary": ProviderConfig("primary", "https://primary.example/v1", "k", "m")}
    gateway = ModelGateway(_settings_with(providers), client=client)

    with pytest.raises(ProviderError):
        await gateway.complete([ChatMessage(role=Role.USER, content="hi")])


@pytest.mark.anyio
async def test_complete_raises_when_chain_is_empty() -> None:
    settings = GatewaySettings(
        llm_primary="nonexistent",
        llm_secondary="",
        llm_local="",
        embed_primary="",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        llm_providers={},
        embed_providers={},
    )
    gateway = ModelGateway(settings)
    with pytest.raises(ProviderError):
        await gateway.complete([ChatMessage(role=Role.USER, content="hi")])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -v`
Expected: FAIL — `model_gateway.gateway` does not exist yet.

- [ ] **Step 3: Write the orchestrator**

Create `packages/model_gateway/src/model_gateway/gateway.py`:

```python
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

import httpx

from model_gateway.pricing import estimate_cost
from model_gateway.providers.anthropic import AnthropicProvider
from model_gateway.providers.base import ChatProvider, EmbeddingProvider
from model_gateway.providers.gemini import GeminiProvider
from model_gateway.providers.huggingface_embed import HuggingFaceEmbeddingProvider
from model_gateway.providers.openai_compatible import OpenAICompatibleProvider
from model_gateway.retry import call_with_retry
from model_gateway.settings import GatewaySettings, ProviderConfig, load_settings
from model_gateway.types import ChatMessage, CompletionResult, EmbeddingResult, ProviderError

logger = logging.getLogger(__name__)


def _build_llm_adapter(
    config: ProviderConfig, *, timeout: float, client: httpx.AsyncClient | None
) -> ChatProvider:
    if config.name == "anthropic":
        return AnthropicProvider(api_key=config.api_key, timeout_seconds=timeout, client=client)
    if config.name == "gemini":
        return GeminiProvider(api_key=config.api_key, timeout_seconds=timeout, client=client)
    return OpenAICompatibleProvider(
        provider_name=config.name,
        base_url=config.base_url,
        api_key=config.api_key,
        timeout_seconds=timeout,
        client=client,
    )


def _build_embed_adapter(
    config: ProviderConfig, *, timeout: float, client: httpx.AsyncClient | None
) -> EmbeddingProvider:
    if config.name == "gemini":
        return GeminiProvider(api_key=config.api_key, timeout_seconds=timeout, client=client)
    if config.name == "huggingface":
        return HuggingFaceEmbeddingProvider(
            api_key=config.api_key, timeout_seconds=timeout, client=client
        )
    return OpenAICompatibleProvider(
        provider_name=config.name,
        base_url=config.base_url,
        api_key=config.api_key,
        timeout_seconds=timeout,
        client=client,
    )


@dataclass
class ChatOutcome:
    result: CompletionResult
    estimated_cost_usd: float
    attempted_providers: list[str]


class ModelGateway:
    def __init__(
        self,
        settings: GatewaySettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or load_settings()
        self._client = client

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> ChatOutcome:
        chain = self._settings.llm_fallback_chain()
        if not chain:
            raise ProviderError("model_gateway", "no LLM providers configured")

        attempted: list[str] = []
        last_error: Exception | None = None
        for provider_name in chain:
            attempted.append(provider_name)
            config = self._settings.llm_providers[provider_name]
            adapter = _build_llm_adapter(
                config, timeout=self._settings.timeout_seconds, client=self._client
            )
            request_id = str(uuid.uuid4())
            try:
                result = await call_with_retry(
                    lambda a=adapter, c=config: a.complete(
                        messages, model=c.model, temperature=temperature, max_tokens=max_tokens
                    ),
                    max_retries=self._settings.max_retries,
                    base_delay_seconds=self._settings.retry_base_delay_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "model_gateway.complete.failed request_id=%s provider=%s error=%s",
                    request_id,
                    provider_name,
                    exc,
                )
                last_error = exc
                continue

            cost = estimate_cost(
                provider=provider_name,
                model=config.model,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cached_input_tokens=result.usage.cached_input_tokens,
            )
            logger.info(
                "model_gateway.complete.success request_id=%s provider=%s model=%s "
                "input_tokens=%d output_tokens=%d cached_input_tokens=%d "
                "estimated_cost_usd=%.6f latency_ms=%.1f",
                request_id,
                provider_name,
                config.model,
                result.usage.input_tokens,
                result.usage.output_tokens,
                result.usage.cached_input_tokens,
                cost,
                result.latency_ms,
            )
            return ChatOutcome(result=result, estimated_cost_usd=cost, attempted_providers=attempted)

        raise ProviderError(
            "model_gateway", f"all providers in fallback chain failed: {attempted}"
        ) from last_error

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        chain = self._settings.embed_fallback_chain()
        if not chain:
            raise ProviderError("model_gateway", "no embedding providers configured")

        last_error: Exception | None = None
        for provider_name in chain:
            config = self._settings.embed_providers[provider_name]
            adapter = _build_embed_adapter(
                config, timeout=self._settings.timeout_seconds, client=self._client
            )
            try:
                return await call_with_retry(
                    lambda a=adapter, c=config: a.embed(texts, model=c.model),
                    max_retries=self._settings.max_retries,
                    base_delay_seconds=self._settings.retry_base_delay_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "model_gateway.embed.failed provider=%s error=%s", provider_name, exc
                )
                last_error = exc
                continue

        raise ProviderError(
            "model_gateway", f"all embedding providers failed: {chain}"
        ) from last_error
```

Modify `packages/model_gateway/src/model_gateway/__init__.py` to re-export the main entrypoint:

```python
from model_gateway.gateway import ChatOutcome, ModelGateway
from model_gateway.types import ChatMessage, Role

__all__ = ["ChatMessage", "ChatOutcome", "ModelGateway", "Role"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -v`
Expected: all tests PASS (previous 25 + 5 new = 30 total).

- [ ] **Step 5: Run quality gates locally**

Run: `ruff check . && black --check . && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/model_gateway/src/model_gateway/gateway.py packages/model_gateway/src/model_gateway/__init__.py packages/model_gateway/tests/test_gateway.py
git commit -m "feat(model-gateway): add ModelGateway orchestrator with fallback, retry, cost, logging"
```

---

### Task 9: CI wiring for packages/model_gateway

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:** none new — this wires Tasks 1–8's package into the existing CI pipeline built in Week 1.

> **Stop and confirm with the user before the branch-protection step below.** Updating required status checks on `main` is a visible, shared-repo-settings change — confirm before running it, per Global Constraints.

- [ ] **Step 1: Add the CI job**

Modify `.github/workflows/ci.yml`, adding a new job alongside the existing `api` and `web` jobs (exact placement doesn't matter; keep it readable — e.g. between them):

```yaml
  model-gateway:
    name: "Model Gateway (lint, type-check, test)"
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: packages/model_gateway
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
git commit -m "ci: add lint/type-check/test job for packages/model_gateway"
```

- [ ] **Step 4: (Controller-level, after this branch is pushed and has a passing CI run) Add the new check to branch protection**

This step is NOT part of the implementer's task — it's done by whoever is running subagent-driven-development, after Task 9's commit is on a pushed branch with a real, passed "Model Gateway (lint, type-check, test)" check visible on GitHub (confirm with the user first, per the note above this task):

```bash
gh api repos/{owner}/{repo}/branches/main/protection \
  --method PUT \
  -f required_status_checks.strict=true \
  -f 'required_status_checks.contexts[]=API (lint, type-check, test)' \
  -f 'required_status_checks.contexts[]=Web (build)' \
  -f 'required_status_checks.contexts[]=Model Gateway (lint, type-check, test)' \
  -f enforce_admins=true \
  -f required_pull_request_reviews=null \
  -f restrictions=null
```
(As in Week 1, `gh api` with dotted `-f` keys for a nested array can fail schema validation — if so, write the JSON body to a file and use `--input` instead, exactly as Week 1's Task 6 did.)
Expected: response JSON lists all three contexts under `required_status_checks.contexts`.

---

## Plan 2a Exit Criteria

- [ ] `packages/model_gateway` has zero-tolerance-clean ruff/black/strict-mypy and a full passing test suite (30 tests), entirely via mocked HTTP — no real network call, no API key needed to run it.
- [ ] All 8 LLM providers and 4 embedding providers are configured and reachable through the same `ModelGateway.complete()`/`.embed()` interface by environment variable alone.
- [ ] Fallback chain (primary → secondary → local) and per-provider retry-before-fallback are both demonstrated by tests, not just claimed.
- [ ] Anthropic prompt caching (`cache_control`) is implemented and tested; OpenAI's automatic caching is correctly surfaced via `cached_tokens` parsing; Gemini's caching plumbing exists but explicit cache creation is deliberately deferred (documented, not silently missing).
- [ ] CI enforces this package the same way it enforces `apps/api` and `apps/web`.
