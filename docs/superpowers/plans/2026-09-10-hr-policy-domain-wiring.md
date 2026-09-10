# HR Policy Domain Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `packages/model_gateway` and `packages/spend_guard` into a real, live `hr_policy` domain endpoint on `apps/api`, provision production Postgres, and deploy — completing the master spec's Week 2 exit criterion.

**Architecture:** Hand-rolled retrieval (chunk the HR policy markdown doc, embed via `model_gateway`, cosine-similarity search) feeds a prompt into `model_gateway.complete()`, gated end-to-end by `spend_guard.precheck()`/`record_success()`/`record_failure()`. Both `spend_guard` and the retrieval index initialize lazily at app startup so a transient upstream failure degrades gracefully instead of crashing the process.

**Tech Stack:** FastAPI, `model_gateway`, `spend_guard`, `numpy` (cosine similarity), `httpx` MockTransport for tests, real local Postgres for `spend_guard` integration tests (no DB mocking, matching every prior plan in this project).

**Spec:** `docs/superpowers/specs/2026-09-10-hr-policy-domain-wiring-design.md` (and the platform master spec it scopes from: `docs/superpowers/specs/2026-09-07-agentic-rag-platform-design.md`)

## Global Constraints

- No governance layer (PII redaction, moderation, audit log) — spec §7 / Week 3. Not in scope.
- No auth — spec's Week 4. The `/ask` endpoint is intentionally open.
- No frontend — Week 4. Verification is via `curl`/integration tests.
- `has_local_fallback=False` for every `hr_policy` Spend Guard call — no Ollama in production, over-budget hard-stops (spec §5 option (b)), never silently downgrades.
- No LlamaIndex. Hand-rolled chunk + embed + cosine similarity only.
- No persistent vector store — in-memory index rebuilt at process start.
- No `packages/retrieval_lite` extraction — this plan's retrieval code lives under `apps/api/src/gateway/domains/hr_policy/`.
- Every SQL/network-touching function that this plan adds to `spend_guard`-adjacent code must follow the existing codebase convention: real local Postgres in tests, no mocking of the DB; `httpx.MockTransport` for all `model_gateway` HTTP calls in tests, no real network in CI.
- All gates (`ruff check .`, `black --check .`, `mypy src`, `pytest -v`) must be clean with zero suppressions (`# type: ignore`, `# noqa`, `pragma: no cover`) in every package/app this plan touches, matching every prior plan in this project.
- Pinned tool versions (already installed in each package's `.venv`): `pytest==9.1.1`, `anyio==4.15.1`, `httpx==0.28.1`, `ruff==0.16.6`, `black==26.5.1`, `mypy==2.3.1`.

---

## Task 1: `model_gateway` — pre-call cost estimate + failure provider attribution

**Files:**
- Modify: `packages/model_gateway/src/model_gateway/types.py` (the `ProviderError` class)
- Modify: `packages/model_gateway/src/model_gateway/gateway.py` (`ModelGateway.complete()`, `ModelGateway.embed()`; add `estimate_precheck_cost()`)
- Test: `packages/model_gateway/tests/test_gateway.py`

**Interfaces:**
- Consumes: existing `ModelGateway.__init__`, `GatewaySettings`, `pricing.estimate_cost()`, `ChatMessage`.
- Produces:
  - `ModelGateway.estimate_precheck_cost(self, messages: list[ChatMessage], *, max_tokens: int) -> float`
  - `ProviderError(provider: str, message: str, *, attempted_providers: list[str] | None = None)` — new keyword-only param, `.attempted_providers` attribute, default `None` (fully backward compatible with every existing raise site).

- [ ] **Step 1: Write the failing tests**

Add to `packages/model_gateway/tests/test_gateway.py` (it already imports `httpx`, `pytest`, `ModelGateway`, `GatewaySettings`, `ProviderConfig`, `ChatMessage`, `ProviderError`, `Role`, and has a `_settings_with(llm_providers, *, secondary="", local="", max_retries=0)` helper — reuse it):

```python
def test_estimate_precheck_cost_uses_primary_provider_and_char_heuristic() -> None:
    providers = {
        "groq": ProviderConfig(
            "groq", "https://api.groq.com/openai/v1", "k", "llama-3.3-70b-versatile"
        ),
    }
    gateway = ModelGateway(_settings_with(providers))
    messages = [
        ChatMessage(role=Role.SYSTEM, content="x" * 400),
        ChatMessage(role=Role.USER, content="y" * 400),
    ]

    cost = gateway.estimate_precheck_cost(messages, max_tokens=100)

    # input_tokens = 800 chars // 4 = 200 (chars/4 heuristic, no tokenizer dependency)
    assert cost == pytest.approx((200 * 0.59 + 100 * 0.79) / 1_000_000)


def test_estimate_precheck_cost_returns_zero_when_chain_is_empty() -> None:
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

    cost = gateway.estimate_precheck_cost(
        [ChatMessage(role=Role.USER, content="hi")], max_tokens=100
    )

    assert cost == 0.0


@pytest.mark.anyio
async def test_complete_raises_provider_error_with_attempted_providers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {
        "primary": ProviderConfig("primary", "https://primary.example/v1", "k", "m"),
        "secondary": ProviderConfig("secondary", "https://secondary.example/v1", "k", "m"),
    }
    gateway = ModelGateway(_settings_with(providers, secondary="secondary"), client=client)

    with pytest.raises(ProviderError) as exc_info:
        await gateway.complete([ChatMessage(role=Role.USER, content="hi")])

    assert exc_info.value.attempted_providers == ["primary", "secondary"]


@pytest.mark.anyio
async def test_embed_raises_provider_error_with_attempted_providers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {
        "primary": ProviderConfig("primary", "https://primary.example/v1", "k", "m"),
        "secondary": ProviderConfig("secondary", "https://secondary.example/v1", "k", "m"),
    }
    settings = GatewaySettings(
        llm_primary="",
        llm_secondary="",
        llm_local="",
        embed_primary="primary",
        embed_secondary="secondary",
        timeout_seconds=5.0,
        max_retries=0,
        retry_base_delay_seconds=0.001,
        llm_providers={},
        embed_providers=providers,
    )
    gateway = ModelGateway(settings, client=client)

    with pytest.raises(ProviderError) as exc_info:
        await gateway.embed(["hi"])

    assert exc_info.value.attempted_providers == ["primary", "secondary"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `packages/model_gateway/.venv/bin/pytest tests/test_gateway.py -v -k "estimate_precheck_cost or attempted_providers"` (from `packages/model_gateway/`)
Expected: FAIL — `estimate_precheck_cost` doesn't exist; `attempted_providers` attribute doesn't exist on `ProviderError`.

- [ ] **Step 3: Implement `ProviderError.attempted_providers`**

In `packages/model_gateway/src/model_gateway/types.py`, replace:

```python
class ProviderError(Exception):
    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}")
```

with:

```python
class ProviderError(Exception):
    def __init__(
        self, provider: str, message: str, *, attempted_providers: list[str] | None = None
    ) -> None:
        self.provider = provider
        self.attempted_providers = attempted_providers
        super().__init__(f"[{provider}] {message}")
```

- [ ] **Step 4: Wire `attempted_providers` into the two full-chain-failure raise sites**

In `packages/model_gateway/src/model_gateway/gateway.py`, in `complete()`, replace:

```python
        raise ProviderError(
            "model_gateway", f"all providers in fallback chain failed: {attempted}"
        ) from last_error
```

with:

```python
        raise ProviderError(
            "model_gateway",
            f"all providers in fallback chain failed: {attempted}",
            attempted_providers=attempted,
        ) from last_error
```

In `embed()`, replace:

```python
        raise ProviderError(
            "model_gateway", f"all embedding providers failed: {attempted}"
        ) from last_error
```

with:

```python
        raise ProviderError(
            "model_gateway",
            f"all embedding providers failed: {attempted}",
            attempted_providers=attempted,
        ) from last_error
```

Do not change the other two `ProviderError`/`ProviderAPIError` raise sites in this file (`force_provider` misconfigured, empty chain) — those have no meaningful `attempted` list and should keep `attempted_providers=None` (the default).

- [ ] **Step 5: Implement `estimate_precheck_cost`**

Add this method to the `ModelGateway` class in `gateway.py`, placed after `embed()`:

```python
    def estimate_precheck_cost(self, messages: list[ChatMessage], *, max_tokens: int) -> float:
        """Conservative pre-call cost estimate for Spend Guard's precheck.

        Uses the primary provider in the fallback chain and a chars/4 input-token
        heuristic (no tokenizer dependency), with max_tokens as the worst-case
        output. Real cost after a call is always computed exactly from actual
        usage by complete()/embed() -- this estimate exists only to let Spend
        Guard reject or allow a call *before* any money is spent.
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

- [ ] **Step 6: Run tests to verify they pass**

Run: `packages/model_gateway/.venv/bin/pytest tests/ -v` (from `packages/model_gateway/`)
Expected: all tests PASS (the 4 new ones plus every pre-existing test unmodified and still green).

- [ ] **Step 7: Run gates**

Run (from `packages/model_gateway/`): `.venv/bin/ruff check .`, `.venv/bin/black --check .`, `.venv/bin/mypy src`
Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add packages/model_gateway/src/model_gateway/types.py packages/model_gateway/src/model_gateway/gateway.py packages/model_gateway/tests/test_gateway.py
git commit -m "feat(model-gateway): add pre-call cost estimate and failure provider attribution"
```

---

## Task 2: `hr_policy` — markdown chunker

**Files:**
- Create: `apps/api/src/gateway/domains/hr_policy/__init__.py` (empty)
- Create: `apps/api/src/gateway/domains/hr_policy/retrieval.py`
- Test: `apps/api/tests/test_hr_policy_retrieval.py`

**Interfaces:**
- Consumes: nothing new (stdlib only).
- Produces:
  - `@dataclass(frozen=True) class Chunk: header: str; text: str; vector: list[float] = field(default_factory=list)`
  - `def chunk_markdown(markdown_text: str) -> list[Chunk]`

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_hr_policy_retrieval.py`:

```python
from __future__ import annotations

from gateway.domains.hr_policy.retrieval import Chunk, chunk_markdown

_SAMPLE_MD = """\
# Acme Corp Policy Manual

## 1. Annual Leave Policy

### 1.1 Entitlement

Full-time employees accrue 20 days of paid annual leave per year.

Leave is accrued monthly and can be taken after the first 90 days.

### 1.2 Leave Carry-Over

Up to 5 unused days may be carried into the next calendar year.

## 2. Remote Work Policy

Employees may work remotely up to 3 days per week with manager approval.
"""


def test_chunk_markdown_tracks_nearest_header_per_paragraph() -> None:
    chunks = chunk_markdown(_SAMPLE_MD)

    assert all(isinstance(c, Chunk) for c in chunks)
    assert [c.header for c in chunks] == [
        "1.1 Entitlement",
        "1.1 Entitlement",
        "1.2 Leave Carry-Over",
        "2. Remote Work Policy",
    ]


def test_chunk_markdown_splits_on_blank_lines_within_a_section() -> None:
    chunks = chunk_markdown(_SAMPLE_MD)

    entitlement_chunks = [c for c in chunks if c.header == "1.1 Entitlement"]
    assert len(entitlement_chunks) == 2
    assert "20 days" in entitlement_chunks[0].text
    assert "90 days" in entitlement_chunks[1].text


def test_chunk_markdown_strips_leading_hashes_from_header() -> None:
    chunks = chunk_markdown(_SAMPLE_MD)

    assert all(not c.header.startswith("#") for c in chunks)


def test_chunk_markdown_skips_empty_sections() -> None:
    md = "# Title\n\n## Empty Section\n\n## Non-Empty Section\n\nSome text here.\n"

    chunks = chunk_markdown(md)

    assert len(chunks) == 1
    assert chunks[0].header == "Non-Empty Section"
    assert chunks[0].text == "Some text here."


def test_chunk_defaults_to_empty_vector() -> None:
    chunks = chunk_markdown("# H\n\nBody text.\n")

    assert chunks[0].vector == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `apps/api/.venv/bin/pytest tests/test_hr_policy_retrieval.py -v` (from `apps/api/`)
Expected: FAIL — `gateway.domains.hr_policy.retrieval` module doesn't exist.

(If `apps/api/.venv` doesn't exist yet, create it first: `python3 -m venv apps/api/.venv && apps/api/.venv/bin/pip install -e "apps/api[dev]"` from the repo root — this will fail until Task 8 adds `model-gateway`/`spend-guard`/`numpy` as dependencies, but Tasks 2-4 don't import those yet, so a plain venv with just `apps/api`'s current `pyproject.toml` deps is sufficient for now.)

- [ ] **Step 3: Implement the chunker**

Create `apps/api/src/gateway/domains/hr_policy/__init__.py` (empty file).

Create `apps/api/src/gateway/domains/hr_policy/retrieval.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chunk:
    header: str
    text: str
    vector: list[float] = field(default_factory=list)


_HEADER_RE = re.compile(r"^#{1,6}\s+(.*)$")


def chunk_markdown(markdown_text: str) -> list[Chunk]:
    """Split a markdown document into (header, paragraph) chunks.

    Tracks the most recently seen heading (any level 1-6) as the citation
    label for every paragraph that follows it, until the next heading.
    Blank lines separate paragraphs within a section. A section with no body
    text before the next heading (or end of document) produces no chunk.
    """
    current_header = ""
    chunks: list[Chunk] = []
    paragraph_lines: list[str] = []

    def flush() -> None:
        text = "\n".join(paragraph_lines).strip()
        if text:
            chunks.append(Chunk(header=current_header, text=text))
        paragraph_lines.clear()

    for line in markdown_text.splitlines():
        header_match = _HEADER_RE.match(line)
        if header_match:
            flush()
            current_header = header_match.group(1).strip()
            continue
        if line.strip() == "":
            flush()
            continue
        paragraph_lines.append(line)
    flush()
    return chunks
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `apps/api/.venv/bin/pytest tests/test_hr_policy_retrieval.py -v` (from `apps/api/`)
Expected: all 5 tests PASS.

- [ ] **Step 5: Run gates**

Run (from `apps/api/`): `.venv/bin/ruff check .`, `.venv/bin/black --check .`, `.venv/bin/mypy src`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/gateway/domains/hr_policy/__init__.py apps/api/src/gateway/domains/hr_policy/retrieval.py apps/api/tests/test_hr_policy_retrieval.py
git commit -m "feat(api): add markdown chunker for hr_policy retrieval"
```

---

## Task 3: `hr_policy` — retrieval index, cosine search, index builder

**Files:**
- Modify: `apps/api/src/gateway/domains/hr_policy/retrieval.py` (append to Task 2's file)
- Create: `apps/api/src/gateway/domains/hr_policy/data/hr_policy.md` (copy of the existing standalone demo's data file)
- Test: `apps/api/tests/test_hr_policy_retrieval.py` (append)

**Interfaces:**
- Consumes: `Chunk` and `chunk_markdown` from Task 2 (same file); `ModelGateway`, `EmbedOutcome` from `model_gateway` (Task 1's package, already released).
- Produces:
  - `class RetrievalIndex: def __init__(self, chunks: list[Chunk]) -> None; def search(self, query_vector: list[float], k: int) -> list[tuple[Chunk, float]]`
  - `async def build_hr_policy_index(gateway: ModelGateway, *, data_path: Path = _DATA_PATH) -> RetrievalIndex`

- [ ] **Step 1: Copy the data file**

```bash
mkdir -p apps/api/src/gateway/domains/hr_policy/data
cp 01-hr-policy-rag/data/hr_policy.md apps/api/src/gateway/domains/hr_policy/data/hr_policy.md
```

- [ ] **Step 2: Write the failing tests**

Append to `apps/api/tests/test_hr_policy_retrieval.py`. Add these imports at the top of the file (alongside the existing `Chunk, chunk_markdown` import):

```python
from __future__ import annotations

import math
from pathlib import Path

import pytest
from model_gateway import ChatMessage, ModelGateway, Role
from model_gateway.settings import GatewaySettings, ProviderConfig

from gateway.domains.hr_policy.retrieval import (
    Chunk,
    RetrievalIndex,
    build_hr_policy_index,
    chunk_markdown,
)
```

(Replace the file's original single-line import with this block; `ChatMessage`/`Role` are only needed if a later test in this file uses them — they aren't, for this task, so omit them: the actual import block for this task is just `Chunk, RetrievalIndex, build_hr_policy_index, chunk_markdown`, plus `math`, `Path`, `pytest`, `ModelGateway`, `GatewaySettings`, `ProviderConfig`, and `httpx` for the mock transport used in `build_hr_policy_index`'s test.)

The precise, final import block for this file after this task is:

```python
from __future__ import annotations

import math
from pathlib import Path

import httpx
import pytest
from model_gateway.gateway import ModelGateway
from model_gateway.settings import GatewaySettings, ProviderConfig

from gateway.domains.hr_policy.retrieval import (
    Chunk,
    RetrievalIndex,
    build_hr_policy_index,
    chunk_markdown,
)
```

Add these tests:

```python
def test_retrieval_index_search_ranks_by_cosine_similarity() -> None:
    chunks = [
        Chunk(header="A", text="a", vector=[1.0, 0.0]),
        Chunk(header="B", text="b", vector=[0.0, 1.0]),
        Chunk(header="C", text="c", vector=[0.9, 0.1]),
    ]
    index = RetrievalIndex(chunks)

    results = index.search([1.0, 0.0], k=2)

    assert [c.header for c, _score in results] == ["A", "C"]
    assert results[0][1] == pytest.approx(1.0)


def test_retrieval_index_search_respects_k() -> None:
    chunks = [
        Chunk(header=str(i), text=str(i), vector=[float(i), 1.0]) for i in range(10)
    ]
    index = RetrievalIndex(chunks)

    results = index.search([5.0, 1.0], k=3)

    assert len(results) == 3


def test_retrieval_index_search_handles_zero_vector_without_crashing() -> None:
    chunks = [Chunk(header="A", text="a", vector=[0.0, 0.0])]
    index = RetrievalIndex(chunks)

    results = index.search([1.0, 0.0], k=1)

    assert results[0][1] == 0.0


@pytest.mark.anyio
async def test_build_hr_policy_index_embeds_every_chunk_and_attaches_vectors(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "hr_policy.md"
    data_path.write_text("# Title\n\n## Section One\n\nFirst paragraph.\n\nSecond paragraph.\n")

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        import json

        texts = json.loads(body)["input"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": i, "embedding": [float(i), 0.0]} for i in range(len(texts))
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {"fake": ProviderConfig("fake", "https://fake.example/v1", "k", "embed-model")}
    settings = GatewaySettings(
        llm_primary="",
        llm_secondary="",
        llm_local="",
        embed_primary="fake",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        retry_base_delay_seconds=0.001,
        llm_providers={},
        embed_providers=providers,
    )
    gateway = ModelGateway(settings, client=client)

    index = await build_hr_policy_index(gateway, data_path=data_path)

    results = index.search([0.0, 0.0], k=2)
    assert len(results) == 2
    assert all(len(chunk.vector) == 2 for chunk, _score in results)


def test_chunk_markdown_parses_the_real_hr_policy_doc() -> None:
    real_path = Path(__file__).parent.parent / "src/gateway/domains/hr_policy/data/hr_policy.md"

    chunks = chunk_markdown(real_path.read_text())

    assert len(chunks) > 10
    assert any("leave" in c.text.lower() for c in chunks)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `apps/api/.venv/bin/pytest tests/test_hr_policy_retrieval.py -v` (from `apps/api/`)
Expected: FAIL — `RetrievalIndex`/`build_hr_policy_index` don't exist yet. (Also install `model-gateway` and `numpy` into `apps/api/.venv` now if not already present: `apps/api/.venv/bin/pip install -e packages/model_gateway -e packages/spend_guard` from the repo root, plus `apps/api/.venv/bin/pip install numpy` — Task 8 formalizes these as real `pyproject.toml` dependencies; installing them ad hoc now unblocks this task's tests.)

- [ ] **Step 4: Implement `RetrievalIndex` and `build_hr_policy_index`**

Append to `apps/api/src/gateway/domains/hr_policy/retrieval.py` (add these imports to the top of the existing file, alongside the Task 2 imports):

```python
from dataclasses import replace
from pathlib import Path

import numpy as np

from model_gateway.gateway import ModelGateway
```

Then append this code to the same file, after `chunk_markdown`:

```python
_DATA_PATH = Path(__file__).parent / "data" / "hr_policy.md"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a = np.array(a, dtype=float)
    vec_b = np.array(b, dtype=float)
    norm_a = float(np.linalg.norm(vec_a))
    norm_b = float(np.linalg.norm(vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


class RetrievalIndex:
    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks

    def search(self, query_vector: list[float], k: int) -> list[tuple[Chunk, float]]:
        scored = [
            (chunk, _cosine_similarity(query_vector, chunk.vector)) for chunk in self._chunks
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


async def build_hr_policy_index(
    gateway: ModelGateway, *, data_path: Path = _DATA_PATH
) -> RetrievalIndex:
    raw_chunks = chunk_markdown(data_path.read_text())
    if not raw_chunks:
        raise ValueError(f"no chunks parsed from {data_path}")
    outcome = await gateway.embed([chunk.text for chunk in raw_chunks])
    embedded = [
        replace(chunk, vector=vector)
        for chunk, vector in zip(raw_chunks, outcome.result.vectors, strict=True)
    ]
    return RetrievalIndex(embedded)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `apps/api/.venv/bin/pytest tests/test_hr_policy_retrieval.py -v` (from `apps/api/`)
Expected: all tests PASS.

- [ ] **Step 6: Run gates**

Run (from `apps/api/`): `.venv/bin/ruff check .`, `.venv/bin/black --check .`, `.venv/bin/mypy src`
Expected: all clean. (`mypy` may need `numpy` type stubs recognized automatically since numpy ships `py.typed`; if `mypy` complains about missing numpy stubs, this indicates the installed numpy version is too old — install `numpy>=1.26`.)

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/gateway/domains/hr_policy/retrieval.py apps/api/src/gateway/domains/hr_policy/data/hr_policy.md apps/api/tests/test_hr_policy_retrieval.py
git commit -m "feat(api): add retrieval index, cosine search, and index builder for hr_policy"
```

---

## Task 4: `hr_policy` — prompt template

**Files:**
- Create: `apps/api/src/gateway/domains/hr_policy/prompts.py`
- Test: `apps/api/tests/test_hr_policy_prompts.py`

**Interfaces:**
- Consumes: `Chunk` from Task 2/3; `ChatMessage`, `Role` from `model_gateway`.
- Produces: `def build_prompt(question: str, retrieved: list[tuple[Chunk, float]]) -> list[ChatMessage]`

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_hr_policy_prompts.py`:

```python
from __future__ import annotations

from model_gateway.types import Role

from gateway.domains.hr_policy.prompts import build_prompt
from gateway.domains.hr_policy.retrieval import Chunk


def test_build_prompt_has_system_and_user_messages() -> None:
    messages = build_prompt("How much leave do I get?", [])

    assert len(messages) == 2
    assert messages[0].role == Role.SYSTEM
    assert messages[1].role == Role.USER


def test_build_prompt_includes_question_and_chunk_headers_and_text() -> None:
    chunks = [
        (Chunk(header="1.1 Entitlement", text="20 days per year."), 0.9),
        (Chunk(header="1.2 Carry-Over", text="Up to 5 days carry over."), 0.8),
    ]

    messages = build_prompt("How much leave do I get?", chunks)

    user_content = messages[1].content
    assert "How much leave do I get?" in user_content
    assert "1.1 Entitlement" in user_content
    assert "20 days per year." in user_content
    assert "1.2 Carry-Over" in user_content
    assert "Up to 5 days carry over." in user_content


def test_build_prompt_system_message_mentions_citation_requirement() -> None:
    messages = build_prompt("q", [])

    assert "cite" in messages[0].content.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `apps/api/.venv/bin/pytest tests/test_hr_policy_prompts.py -v` (from `apps/api/`)
Expected: FAIL — `gateway.domains.hr_policy.prompts` doesn't exist.

- [ ] **Step 3: Implement**

Create `apps/api/src/gateway/domains/hr_policy/prompts.py`:

```python
from __future__ import annotations

from model_gateway.types import ChatMessage, Role

from gateway.domains.hr_policy.retrieval import Chunk

_SYSTEM_PROMPT = (
    "You are a knowledgeable HR assistant for Acme Corp employees. Answer the "
    "question accurately and concisely based only on the provided HR policy "
    "context below. If the policy is silent on a topic, say so clearly rather "
    "than guessing. Always cite the specific policy section by name."
)


def build_prompt(question: str, retrieved: list[tuple[Chunk, float]]) -> list[ChatMessage]:
    context_blocks = "\n\n".join(f"[{chunk.header}]\n{chunk.text}" for chunk, _score in retrieved)
    user_content = (
        f"Policy context:\n{context_blocks}\n\n"
        f"Employee question: {question}\n\n"
        "Answer (include section reference):"
    )
    return [
        ChatMessage(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
        ChatMessage(role=Role.USER, content=user_content),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `apps/api/.venv/bin/pytest tests/test_hr_policy_prompts.py -v` (from `apps/api/`)
Expected: all 3 tests PASS.

- [ ] **Step 5: Run gates**

Run (from `apps/api/`): `.venv/bin/ruff check .`, `.venv/bin/black --check .`, `.venv/bin/mypy src`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/gateway/domains/hr_policy/prompts.py apps/api/tests/test_hr_policy_prompts.py
git commit -m "feat(api): add hr_policy prompt template"
```

---

## Task 5: `apps/api` — lazy resource resolution + shared dependency providers

**Files:**
- Create: `apps/api/src/gateway/lazy.py`
- Create: `apps/api/src/gateway/dependencies.py`
- Test: `apps/api/tests/test_lazy.py`

**Interfaces:**
- Consumes: `ModelGateway` from `model_gateway`; `SpendGuard`, `create_spend_guard` from `spend_guard`.
- Produces:
  - `@dataclass class LazyResource(Generic[T]): value: T | None = None; build_error: str | None = None; lock: asyncio.Lock = field(default_factory=asyncio.Lock)`
  - `async def resolve_lazy(resource: LazyResource[T], build: Callable[[], Awaitable[T]], *, error_detail: str) -> T` (raises `fastapi.HTTPException(503, detail=error_detail)` on build failure)
  - `async def get_spend_guard(request: Request) -> SpendGuard` (reads `request.app.state.spend_guard: LazyResource[SpendGuard]`)
  - `async def get_model_gateway(request: Request) -> ModelGateway` (reads `request.app.state.gateway: ModelGateway`)

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_lazy.py`. Both `get_model_gateway`/`get_spend_guard` tests construct a bare Starlette `Request` against a manually-populated `app.state` rather than spinning up real HTTP, since these dependency functions only ever read `request.app.state`, never the request body or headers — the simplest correct way to unit-test a `Request`-typed dependency function in isolation:

```python
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request as StarletteRequest

from gateway.dependencies import get_model_gateway, get_spend_guard
from gateway.lazy import LazyResource, resolve_lazy


@pytest.mark.anyio
async def test_resolve_lazy_returns_cached_value_without_rebuilding() -> None:
    build_calls = {"count": 0}

    async def build() -> str:
        build_calls["count"] += 1
        return "built"

    resource: LazyResource[str] = LazyResource(value="cached")

    result = await resolve_lazy(resource, build, error_detail="nope")

    assert result == "cached"
    assert build_calls["count"] == 0


@pytest.mark.anyio
async def test_resolve_lazy_builds_and_caches_on_first_use() -> None:
    async def build() -> str:
        return "built"

    resource: LazyResource[str] = LazyResource()

    result = await resolve_lazy(resource, build, error_detail="nope")

    assert result == "built"
    assert resource.value == "built"
    assert resource.build_error is None


@pytest.mark.anyio
async def test_resolve_lazy_raises_503_and_records_error_on_build_failure() -> None:
    async def build() -> str:
        raise RuntimeError("boom")

    resource: LazyResource[str] = LazyResource()

    with pytest.raises(HTTPException) as exc_info:
        await resolve_lazy(resource, build, error_detail="unavailable")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "unavailable"
    assert resource.value is None
    assert resource.build_error == "boom"


@pytest.mark.anyio
async def test_resolve_lazy_recovers_after_a_prior_failed_attempt() -> None:
    attempt = {"count": 0}

    async def build() -> str:
        attempt["count"] += 1
        if attempt["count"] == 1:
            raise RuntimeError("first attempt fails")
        return "recovered"

    resource: LazyResource[str] = LazyResource()

    with pytest.raises(HTTPException):
        await resolve_lazy(resource, build, error_detail="unavailable")

    result = await resolve_lazy(resource, build, error_detail="unavailable")

    assert result == "recovered"
    assert resource.build_error is None


def test_get_model_gateway_reads_app_state() -> None:
    app = FastAPI()
    app.state.gateway = "fake-gateway-object"

    async def _check() -> None:
        request = StarletteRequest({"type": "http", "app": app})
        result = await get_model_gateway(request)
        assert result == "fake-gateway-object"

    asyncio.run(_check())


def test_get_spend_guard_resolves_via_lazy_resource() -> None:
    app = FastAPI()
    app.state.spend_guard = LazyResource(value="fake-spend-guard-object")

    async def _check() -> None:
        request = StarletteRequest({"type": "http", "app": app})
        result = await get_spend_guard(request)
        assert result == "fake-spend-guard-object"

    asyncio.run(_check())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `apps/api/.venv/bin/pytest tests/test_lazy.py -v` (from `apps/api/`)
Expected: FAIL — `gateway.lazy`/`gateway.dependencies` don't exist.

- [ ] **Step 3: Implement `gateway/lazy.py`**

```python
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from fastapi import HTTPException

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class LazyResource(Generic[T]):
    value: T | None = None
    build_error: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def resolve_lazy(
    resource: LazyResource[T], build: Callable[[], Awaitable[T]], *, error_detail: str
) -> T:
    if resource.value is not None:
        return resource.value
    async with resource.lock:
        if resource.value is not None:
            return resource.value
        try:
            built = await build()
        except Exception as exc:
            resource.build_error = str(exc)
            logger.critical("gateway.lazy_rebuild_failed error=%s", exc)
            raise HTTPException(status_code=503, detail=error_detail) from exc
        resource.value = built
        resource.build_error = None
        return built
```

- [ ] **Step 4: Implement `gateway/dependencies.py`**

```python
from __future__ import annotations

from fastapi import Request
from model_gateway.gateway import ModelGateway
from spend_guard.guard import SpendGuard, create_spend_guard

from gateway.lazy import resolve_lazy


async def get_model_gateway(request: Request) -> ModelGateway:
    gateway: ModelGateway = request.app.state.gateway
    return gateway


async def get_spend_guard(request: Request) -> SpendGuard:
    return await resolve_lazy(
        request.app.state.spend_guard,
        create_spend_guard,
        error_detail="Spend Guard is temporarily unavailable.",
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `apps/api/.venv/bin/pytest tests/test_lazy.py -v` (from `apps/api/`)
Expected: all 6 tests PASS.

- [ ] **Step 6: Run gates**

Run (from `apps/api/`): `.venv/bin/ruff check .`, `.venv/bin/black --check .`, `.venv/bin/mypy src`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/gateway/lazy.py apps/api/src/gateway/dependencies.py apps/api/tests/test_lazy.py
git commit -m "feat(api): add lazy resource resolution and shared dependency providers"
```

---

## Task 6: `hr_policy` — the `/ask` endpoint

**Files:**
- Create: `apps/api/src/gateway/domains/hr_policy/router.py`
- Create: `apps/api/tests/conftest.py`
- Test: `apps/api/tests/test_hr_policy_router.py`

**Interfaces:**
- Consumes: `Chunk`, `RetrievalIndex`, `build_hr_policy_index` (Task 3); `build_prompt` (Task 4); `LazyResource`, `resolve_lazy` (Task 5's `gateway.lazy`); `get_model_gateway`, `get_spend_guard` (Task 5's `gateway.dependencies`); `ModelGateway`, `ChatMessage`, `ProviderError`, `estimate_precheck_cost` (Task 1's `model_gateway`); `SpendGuard`, `SpendDecision`, `create_spend_guard` (`spend_guard`).
- Produces:
  - `router: APIRouter` (module-level, `prefix="/api/v1/hr_policy"`)
  - `async def get_hr_policy_index(request: Request) -> RetrievalIndex`
  - `POST /api/v1/hr_policy/ask` — request `{"question": str}`, success response `{"answer": str, "sources": [{"header": str, "excerpt": str, "relevance": float}], "provider_used": str}` (200), failure responses per spec §4.5 (503 with a specific `detail`).

- [ ] **Step 1: Write `apps/api/tests/conftest.py`**

This bootstraps a real local Postgres test database for `spend_guard`, following the exact pattern already established in `packages/spend_guard/tests/conftest.py`:

```python
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from spend_guard.guard import SpendGuard, create_spend_guard
from spend_guard.schema import apply_schema

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vinoth@localhost:5432/gateway_test"
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _admin_dsn_and_db_name() -> tuple[str, str]:
    parts = urlsplit(TEST_DATABASE_URL)
    db_name = parts.path.lstrip("/")
    admin_dsn = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))
    return admin_dsn, db_name


async def _ensure_database_exists() -> None:
    admin_dsn, db_name = _admin_dsn_and_db_name()
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
        await apply_schema(conn)
    finally:
        await conn.close()


def pytest_configure(config: pytest.Config) -> None:
    asyncio.run(_ensure_database_exists())
    asyncio.run(_apply_schema())


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
async def real_spend_guard(clean_db: None) -> AsyncIterator[SpendGuard]:
    guard = await create_spend_guard(
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
        yield guard
    finally:
        await guard.aclose()


@pytest.fixture
async def zero_budget_spend_guard(clean_db: None) -> AsyncIterator[SpendGuard]:
    """A SpendGuard whose daily cap is already exhausted by any positive spend.

    A dedicated fixture rather than mutating real_spend_guard's private fields
    in a test -- SpendGuard's public contract has no cap-mutation method, and
    reaching into `_daily_cap_usd` from test code would need a
    `# type: ignore[attr-defined]` to pass strict mypy, which this project
    treats as a real code-quality defect, not a convenience.
    """
    guard = await create_spend_guard(
        TEST_DATABASE_URL,
        env={
            "SPEND_GUARD_DAILY_CAP_USD": "0.0",
            "SPEND_GUARD_MONTHLY_CAP_USD": "0.0",
            "SPEND_GUARD_CIRCUIT_BREAKER_THRESHOLD": "3",
            "SPEND_GUARD_CIRCUIT_BREAKER_COOLDOWN_SECONDS": "300",
            "SPEND_GUARD_VELOCITY_THRESHOLD_USD_PER_MINUTE": "100.0",
        },
    )
    try:
        yield guard
    finally:
        await guard.aclose()
```

`SPEND_GUARD_VELOCITY_THRESHOLD_USD_PER_MINUTE` is deliberately high here (matching `packages/spend_guard/tests/test_guard.py`'s own `guard` fixture) so budget-cap tests aren't accidentally tripped by the velocity check, which runs before the budget check inside `precheck()`.

- [ ] **Step 2: Write the failing tests**

Create `apps/api/tests/test_hr_policy_router.py`:

```python
from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from model_gateway.gateway import ModelGateway
from model_gateway.settings import GatewaySettings, ProviderConfig
from spend_guard.guard import SpendDecision, SpendGuard

from gateway.dependencies import get_model_gateway, get_spend_guard
from gateway.domains.hr_policy.retrieval import Chunk, RetrievalIndex
from gateway.domains.hr_policy.router import get_hr_policy_index, router


def _chat_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def _embed_response(n: int) -> httpx.Response:
    return httpx.Response(
        200, json={"data": [{"index": i, "embedding": [1.0, 0.0]} for i in range(n)]}
    )


def _build_app(
    *, gateway: ModelGateway, spend_guard: SpendGuard, index: RetrievalIndex
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_model_gateway] = lambda: gateway
    app.dependency_overrides[get_spend_guard] = lambda: spend_guard
    app.dependency_overrides[get_hr_policy_index] = lambda: index
    return app


def _fake_gateway(
    transport_handler: Callable[[httpx.Request], httpx.Response],
) -> ModelGateway:
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport_handler))
    providers = {
        "groq": ProviderConfig("groq", "https://api.groq.com/openai/v1", "k", "llama-3.3-70b-versatile"),
    }
    embed_providers = {
        "gemini": ProviderConfig("gemini", "https://fake.example/v1", "k", "text-embedding-004"),
    }
    settings = GatewaySettings(
        llm_primary="groq",
        llm_secondary="",
        llm_local="",
        embed_primary="gemini",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        retry_base_delay_seconds=0.001,
        llm_providers=providers,
        embed_providers=embed_providers,
    )
    return ModelGateway(settings, client=client)


_INDEX = RetrievalIndex(
    [Chunk(header="1.1 Entitlement", text="20 days per year.", vector=[1.0, 0.0])]
)


@pytest.mark.anyio
async def test_ask_returns_answer_with_sources_on_success(real_spend_guard: SpendGuard) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "embeddings" in str(request.url):
            return _embed_response(1)
        return _chat_response("You get 20 days per year. [1.1 Entitlement]")

    gateway = _fake_gateway(handler)
    app = _build_app(gateway=gateway, spend_guard=real_spend_guard, index=_INDEX)

    with TestClient(app) as client:
        response = client.post("/api/v1/hr_policy/ask", json={"question": "How much leave?"})

    assert response.status_code == 200
    body = response.json()
    assert "20 days" in body["answer"]
    assert body["sources"][0]["header"] == "1.1 Entitlement"
    assert body["provider_used"] == "groq"


@pytest.mark.anyio
async def test_ask_returns_503_when_budget_exceeded(
    zero_budget_spend_guard: SpendGuard,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "embeddings" in str(request.url):
            return _embed_response(1)
        return _chat_response("answer")

    gateway = _fake_gateway(handler)
    app = _build_app(gateway=gateway, spend_guard=zero_budget_spend_guard, index=_INDEX)

    with TestClient(app) as client:
        response = client.post("/api/v1/hr_policy/ask", json={"question": "How much leave?"})

    assert response.status_code == 503
    assert "budget" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_ask_falls_back_to_secondary_provider_and_reports_it(
    real_spend_guard: SpendGuard,
) -> None:
    call_count = {"groq": 0, "gemini_chat": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "embeddings" in url:
            return _embed_response(1)
        if "groq" in url or "primary" in url:
            call_count["groq"] += 1
            return httpx.Response(500, text="boom")
        call_count["gemini_chat"] += 1
        return _chat_response("fallback answer")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {
        "groq": ProviderConfig("groq", "https://api.groq.com/openai/v1", "k", "llama-3.3-70b-versatile"),
        "gemini": ProviderConfig("gemini", "https://fake.example/v1beta", "k", "gemini-2.0-flash"),
    }
    embed_providers = {
        "gemini": ProviderConfig("gemini", "https://fake.example/v1", "k", "text-embedding-004"),
    }
    settings = GatewaySettings(
        llm_primary="groq",
        llm_secondary="gemini",
        llm_local="",
        embed_primary="gemini",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        retry_base_delay_seconds=0.001,
        llm_providers=providers,
        embed_providers=embed_providers,
    )
    gateway = ModelGateway(settings, client=client)
    app = _build_app(gateway=gateway, spend_guard=real_spend_guard, index=_INDEX)

    with TestClient(app) as client_http:
        response = client_http.post("/api/v1/hr_policy/ask", json={"question": "q"})

    assert response.status_code == 200
    assert response.json()["provider_used"] == "gemini"
    assert call_count["groq"] == 1
    assert call_count["gemini_chat"] == 1


@pytest.mark.anyio
async def test_ask_returns_503_and_records_failure_when_all_providers_fail(
    real_spend_guard: SpendGuard,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "embeddings" in str(request.url):
            return _embed_response(1)
        return httpx.Response(500, text="boom")

    gateway = _fake_gateway(handler)
    app = _build_app(gateway=gateway, spend_guard=real_spend_guard, index=_INDEX)

    with TestClient(app) as client:
        response = client.post("/api/v1/hr_policy/ask", json={"question": "q"})

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
    assert await real_spend_guard.is_provider_available(provider="groq") is True  # 1 failure, threshold 3


@pytest.mark.anyio
async def test_precheck_never_returns_downgrade_to_local_for_hr_policy(
    zero_budget_spend_guard: SpendGuard,
) -> None:
    decision = await zero_budget_spend_guard.precheck(0.01, has_local_fallback=False)

    assert decision != SpendDecision.DOWNGRADE_TO_LOCAL
    assert decision == SpendDecision.BLOCK_BUDGET_EXCEEDED
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `apps/api/.venv/bin/pytest tests/test_hr_policy_router.py -v` (from `apps/api/`, with a real local Postgres reachable at `TEST_DATABASE_URL`)
Expected: FAIL — `gateway.domains.hr_policy.router` doesn't exist.

- [ ] **Step 4: Implement `router.py`**

```python
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from model_gateway.gateway import ModelGateway
from model_gateway.types import ProviderError
from pydantic import BaseModel
from spend_guard.guard import SpendDecision, SpendGuard

from gateway.dependencies import get_model_gateway, get_spend_guard
from gateway.domains.hr_policy.prompts import build_prompt
from gateway.domains.hr_policy.retrieval import RetrievalIndex, build_hr_policy_index
from gateway.lazy import resolve_lazy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/hr_policy", tags=["hr_policy"])

_TOP_K = 4
_MAX_TOKENS = 512
_EXCERPT_MAX_CHARS = 200


class AskRequest(BaseModel):
    question: str


class Source(BaseModel):
    header: str
    excerpt: str
    relevance: float


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    provider_used: str


async def get_hr_policy_index(request: Request) -> RetrievalIndex:
    gateway: ModelGateway = request.app.state.gateway

    async def _build() -> RetrievalIndex:
        return await build_hr_policy_index(gateway)

    return await resolve_lazy(
        request.app.state.hr_policy_index,
        _build,
        error_detail="hr_policy is temporarily unavailable",
    )


def _last_attempted_provider(exc: ProviderError) -> str:
    return exc.attempted_providers[-1] if exc.attempted_providers else "unknown"


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    index: RetrievalIndex = Depends(get_hr_policy_index),
    gateway: ModelGateway = Depends(get_model_gateway),
    spend_guard: SpendGuard = Depends(get_spend_guard),
) -> AskResponse:
    try:
        embed_outcome = await gateway.embed([body.question])
    except ProviderError as exc:
        await spend_guard.record_failure(provider=_last_attempted_provider(exc))
        raise HTTPException(
            status_code=503, detail="hr_policy is temporarily unavailable"
        ) from exc

    await spend_guard.record_success(
        embed_outcome.estimated_cost_usd,
        domain="hr_policy",
        provider=embed_outcome.result.provider,
    )

    query_vector = embed_outcome.result.vectors[0]
    retrieved = index.search(query_vector, _TOP_K)
    messages = build_prompt(body.question, retrieved)

    estimate = gateway.estimate_precheck_cost(messages, max_tokens=_MAX_TOKENS)
    decision = await spend_guard.precheck(estimate, has_local_fallback=False)
    if decision == SpendDecision.BLOCK_BUDGET_EXCEEDED:
        raise HTTPException(
            status_code=503,
            detail="Daily budget for hr_policy has been reached. Try again tomorrow.",
        )
    if decision == SpendDecision.BLOCK_GLOBAL_BREAKER:
        raise HTTPException(
            status_code=503,
            detail="hr_policy is temporarily unavailable (circuit breaker open).",
        )
    if decision == SpendDecision.BLOCK_VELOCITY_SPIKE:
        raise HTTPException(
            status_code=503,
            detail="hr_policy is temporarily unavailable (unusual spend velocity detected).",
        )

    try:
        outcome = await gateway.complete(messages, max_tokens=_MAX_TOKENS)
    except ProviderError as exc:
        await spend_guard.record_failure(provider=_last_attempted_provider(exc))
        raise HTTPException(
            status_code=503,
            detail="hr_policy is temporarily unavailable (all providers failed).",
        ) from exc

    await spend_guard.record_success(
        outcome.estimated_cost_usd, domain="hr_policy", provider=outcome.result.provider
    )

    sources = [
        Source(
            header=chunk.header,
            excerpt=chunk.text[:_EXCERPT_MAX_CHARS]
            + ("..." if len(chunk.text) > _EXCERPT_MAX_CHARS else ""),
            relevance=score,
        )
        for chunk, score in retrieved
    ]
    return AskResponse(
        answer=outcome.result.text, sources=sources, provider_used=outcome.result.provider
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `apps/api/.venv/bin/pytest tests/test_hr_policy_router.py -v` (from `apps/api/`)
Expected: all 5 tests PASS. If `test_ask_returns_503_when_budget_exceeded` or the fallback test are flaky, check that `real_spend_guard`'s velocity threshold (100.0) is high enough relative to the tiny cost estimates involved — it already is, per the fixture's design.

- [ ] **Step 6: Run gates**

Run (from `apps/api/`): `.venv/bin/ruff check .`, `.venv/bin/black --check .`, `.venv/bin/mypy src`
Expected: all clean. Also run `.venv/bin/pytest tests/ -v` (the whole suite) to confirm nothing in Tasks 2-5 regressed.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/gateway/domains/hr_policy/router.py apps/api/tests/conftest.py apps/api/tests/test_hr_policy_router.py
git commit -m "feat(api): add hr_policy /ask endpoint wiring model_gateway and spend_guard"
```

---

## Task 7: `apps/api` — lifespan wiring, router mounting, scaffold-test update

**Files:**
- Modify: `apps/api/src/gateway/main.py`
- Modify: `apps/api/tests/test_domains.py`
- Test: `apps/api/tests/test_main_wiring.py` (new)

**Interfaces:**
- Consumes: everything from Tasks 1-6 (`get_model_gateway`, `get_spend_guard` from `gateway.dependencies`; `get_hr_policy_index`, `router` from `gateway.domains.hr_policy.router`; `LazyResource` from `gateway.lazy`; `build_hr_policy_index` from `gateway.domains.hr_policy.retrieval`; `ModelGateway` from `model_gateway`; `SpendGuard`, `create_spend_guard` from `spend_guard`).
- Produces: `create_app() -> FastAPI` (unchanged signature, new internal wiring), `lifespan` (new).

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_main_wiring.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient
from model_gateway.gateway import ModelGateway
from model_gateway.settings import GatewaySettings

from gateway.dependencies import get_model_gateway, get_spend_guard
from gateway.domains.hr_policy.retrieval import Chunk, RetrievalIndex
from gateway.domains.hr_policy.router import get_hr_policy_index
from gateway.main import create_app


def _empty_gateway() -> ModelGateway:
    settings = GatewaySettings(
        llm_primary="",
        llm_secondary="",
        llm_local="",
        embed_primary="",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        llm_providers={},
        embed_providers={},
    )
    return ModelGateway(settings)


def test_hr_policy_ask_route_is_mounted_not_the_scaffold() -> None:
    app = create_app()
    app.dependency_overrides[get_model_gateway] = _empty_gateway
    app.dependency_overrides[get_spend_guard] = lambda: None
    app.dependency_overrides[get_hr_policy_index] = lambda: RetrievalIndex(
        [Chunk(header="H", text="T", vector=[1.0])]
    )

    client = TestClient(app)
    response = client.get("/api/v1/hr_policy/status")

    # The scaffold's /status route no longer exists for hr_policy -- only /ask does.
    assert response.status_code == 404


def test_other_domains_still_scaffolded() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/contract_review/status")

    assert response.status_code == 200
    assert response.json() == {"domain": "contract_review", "status": "scaffolded"}


def test_health_still_ok_without_lifespan() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `apps/api/.venv/bin/pytest tests/test_main_wiring.py -v` (from `apps/api/`)
Expected: FAIL — `hr_policy` is still mounted as the generic scaffold router (its `/status` route returns 200, not 404).

- [ ] **Step 3: Implement `main.py`**

Replace the full contents of `apps/api/src/gateway/main.py`:

```python
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from model_gateway.gateway import ModelGateway
from spend_guard.guard import SpendGuard, create_spend_guard

from gateway.domains.hr_policy.retrieval import RetrievalIndex, build_hr_policy_index
from gateway.domains.hr_policy.router import router as hr_policy_router
from gateway.domains.registry import DOMAIN_NAMES, make_domain_router
from gateway.lazy import LazyResource

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    gateway = ModelGateway()
    app.state.gateway = gateway

    spend_guard_resource: LazyResource[SpendGuard] = LazyResource()
    try:
        spend_guard_resource.value = await create_spend_guard()
    except Exception as exc:
        logger.critical("gateway.startup.spend_guard_init_failed error=%s", exc)
        spend_guard_resource.build_error = str(exc)
    app.state.spend_guard = spend_guard_resource

    hr_policy_index_resource: LazyResource[RetrievalIndex] = LazyResource()
    try:
        hr_policy_index_resource.value = await build_hr_policy_index(gateway)
    except Exception as exc:
        logger.critical("hr_policy.startup.index_build_failed error=%s", exc)
        hr_policy_index_resource.build_error = str(exc)
    app.state.hr_policy_index = hr_policy_index_resource

    yield

    if spend_guard_resource.value is not None:
        await spend_guard_resource.value.aclose()
    await gateway.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Portfolio Gateway", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for name in DOMAIN_NAMES:
        if name == "hr_policy":
            app.include_router(hr_policy_router)
        else:
            app.include_router(make_domain_router(name))

    return app


app = create_app()
```

- [ ] **Step 4: Update `test_domains.py`**

Replace the full contents of `apps/api/tests/test_domains.py`:

```python
import pytest
from fastapi.testclient import TestClient

from gateway.domains.registry import DOMAIN_NAMES
from gateway.main import create_app

_SCAFFOLDED_DOMAINS = [name for name in DOMAIN_NAMES if name != "hr_policy"]


@pytest.mark.parametrize("domain", _SCAFFOLDED_DOMAINS)
def test_domain_status_endpoint(domain: str) -> None:
    client = TestClient(create_app())
    response = client.get(f"/api/v1/{domain}/status")
    assert response.status_code == 200
    assert response.json() == {"domain": domain, "status": "scaffolded"}


def test_domain_names_match_spec() -> None:
    assert DOMAIN_NAMES == [
        "hr_policy",
        "contract_review",
        "marketing_hub",
        "techdocs",
        "it_helpdesk",
    ]


def test_hr_policy_is_no_longer_scaffolded() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/hr_policy/status")
    assert response.status_code == 404
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `apps/api/.venv/bin/pytest tests/ -v` (from `apps/api/`, the whole suite)
Expected: all tests PASS, including every test from Tasks 2-6 still green.

- [ ] **Step 6: Run gates**

Run (from `apps/api/`): `.venv/bin/ruff check .`, `.venv/bin/black --check .`, `.venv/bin/mypy src`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/gateway/main.py apps/api/tests/test_domains.py apps/api/tests/test_main_wiring.py
git commit -m "feat(api): wire hr_policy router and lazy startup into main.py"
```

---

## Task 8: Dependencies, `py.typed` markers, strict mypy, CI, Docker, env docs

**Files:**
- Modify: `apps/api/pyproject.toml`
- Create: `packages/model_gateway/src/model_gateway/py.typed`
- Create: `packages/spend_guard/src/spend_guard/py.typed`
- Modify: `.github/workflows/ci.yml` (the `api` job)
- Modify: `apps/api/Dockerfile`
- Modify: `render.yaml`
- Create: `.dockerignore` (repo root)
- Delete: `apps/api/.dockerignore`
- Modify: `.env.example`

**Interfaces:** None (infra-only; no new Python interfaces).

This task has no TDD cycle in the usual sense (it's dependency/infra wiring, not new logic) — each step below is independently verifiable by a concrete command.

- [ ] **Step 1: Add `py.typed` markers**

```bash
touch packages/model_gateway/src/model_gateway/py.typed
touch packages/spend_guard/src/spend_guard/py.typed
```

This is required for `apps/api`'s strict mypy to type-check `model_gateway`/`spend_guard` imports correctly rather than treating them as untyped `Any` — verified empirically: without this marker, `mypy --strict` on a file importing `model_gateway` reports `error: Skipping analyzing "model_gateway": module is installed, but missing library stubs or py.typed marker [import-untyped]` and every name imported from it resolves to `Any`. Both packages' `[tool.hatch.build.targets.wheel]` sections already list `packages = ["src/model_gateway"]` / `packages = ["src/spend_guard"]`, so hatchling includes this new file in the built wheel automatically — no other packaging config changes needed.

- [ ] **Step 2: Update `apps/api/pyproject.toml`**

Replace the file's contents:

```toml
[project]
name = "gateway"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "model-gateway",
    "spend-guard",
    "numpy>=1.26,<3",
]

[project.optional-dependencies]
dev = [
    "pytest==9.1.1",
    "anyio==4.15.1",
    "httpx==0.28.1",
    "ruff==0.16.6",
    "black==26.5.1",
    "mypy==2.3.1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/gateway"]

[tool.hatch.build.targets.wheel.force-include]
"src/gateway/domains/hr_policy/data/hr_policy.md" = "gateway/domains/hr_policy/data/hr_policy.md"

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

Notes on the changes: `model-gateway`/`spend-guard` are listed by package name only (no version pin, no path) — they're satisfied by whichever local editable install is already present (see Step 3), matching how every other cross-package dependency in this monorepo works, since there's no private package index. `numpy` gets a real version floor. `mypy` config is replaced with `strict = true`, matching `model_gateway`/`spend_guard`'s own config, since `apps/api` now has real domain logic worth the same rigor. The `force-include` entry ensures `hatchling`'s default `packages = ["src/gateway"]` behavior (which only picks up `.py` files under that path via its module-discovery, not the `data/hr_policy.md` non-Python asset) still ships the markdown data file in a built wheel — verify this in Step 8 below rather than assuming it.

- [ ] **Step 3: Install sibling packages into `apps/api`'s local dev venv**

```bash
apps/api/.venv/bin/pip install -e packages/model_gateway -e packages/spend_guard -e "apps/api[dev]"
```

(Run from the repo root. If `apps/api/.venv` doesn't exist yet: `python3 -m venv apps/api/.venv` first.)

- [ ] **Step 4: Re-run the full apps/api test suite and gates under the new strict mypy config**

Run (from `apps/api/`): `.venv/bin/pytest tests/ -v`, `.venv/bin/ruff check .`, `.venv/bin/black --check .`, `.venv/bin/mypy src`
Expected: all clean. If `mypy --strict` surfaces issues in code written during Tasks 2-7 (e.g. a missing return type on a helper, an implicit `Any`), fix them directly in this step — small, mechanical typing fixes only, not logic changes. Every code sample in Tasks 1-7 above was written with full type annotations specifically so this step should be a no-op verification, not a rework.

- [ ] **Step 5: Update `.github/workflows/ci.yml`'s `api` job**

Replace the `api` job in `.github/workflows/ci.yml` with:

```yaml
  api:
    name: "API (lint, type-check, test)"
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: gateway_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    defaults:
      run:
        working-directory: apps/api
    env:
      TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/gateway_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install sibling packages
        run: |
          pip install -e ../../packages/model_gateway
          pip install -e ../../packages/spend_guard
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

Do not modify the `model-gateway`, `spend-guard`, or `web` jobs — this task only touches `api`.

- [ ] **Step 6: Rewrite `apps/api/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY packages/model_gateway ./packages/model_gateway
COPY packages/spend_guard ./packages/spend_guard
COPY apps/api ./apps/api

RUN pip install --no-cache-dir ./packages/model_gateway ./packages/spend_guard ./apps/api

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8080

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

This Dockerfile now expects to be built with the **repo root** as the build context (not `apps/api`), since it needs to `COPY` sibling package directories — see the `render.yaml` change in Step 7.

- [ ] **Step 7: Update `render.yaml`**

Replace `render.yaml`'s contents (repo root):

```yaml
services:
  - type: web
    name: rag-portfolio-api
    runtime: docker
    dockerfilePath: apps/api/Dockerfile
    dockerContext: .
    plan: free
    healthCheckPath: /health
    envVars:
      - key: DATABASE_URL
        sync: false
      - key: GROQ_API_KEY
        sync: false
      - key: GEMINI_API_KEY
        sync: false
      - key: LLM_PROVIDER_SECONDARY
        value: gemini
      - key: EMBED_PROVIDER
        value: gemini
```

`dockerContext: .` (repo root) combined with `dockerfilePath: apps/api/Dockerfile` is Render's documented mechanism for a Dockerfile that needs to `COPY` sibling directories outside its own service folder in a monorepo (verified against Render's Blueprint spec docs) — `rootDir` (the field this replaced) only affects which file changes trigger an automatic redeploy, not the Docker build context itself, so removing it is correct, not a regression. The `sync: false` vars are secrets set manually in Render's dashboard (Task 10), never committed; `LLM_PROVIDER_SECONDARY`/`EMBED_PROVIDER` have real values here because they're not secrets and `model_gateway`'s own defaults (`embed_primary` defaults to `ollama`, which doesn't exist on Render) are wrong for this deployment.

- [ ] **Step 8: Root `.dockerignore` and remove the stale one**

```bash
rm apps/api/.dockerignore
```

Create `.dockerignore` at the repo root:

```
.git/
.claude/
docs/
apps/web/
01-hr-policy-rag/
02-contract-review-chat/
03-marketing-content-hub/
04-techDocs-rag-pipeline/
05-it-helpdesk-agent/
**/.venv/
**/__pycache__/
**/*.pyc
**/.pytest_cache/
**/.mypy_cache/
**/.ruff_cache/
**/tests/
```

With `dockerContext: .`, Docker looks for `.dockerignore` at the build context root (the repo root), not `apps/api/.dockerignore` — the old file is now dead and would be silently ignored if left in place, so it's removed rather than kept alongside a misleading stale copy.

- [ ] **Step 9: Verify the Docker build locally**

```bash
docker build -f apps/api/Dockerfile -t rag-api-test .
docker run --rm -p 8080:8080 -e DATABASE_URL="postgresql://invalid/doesnotmatter" -e GEMINI_API_KEY="" -e GROQ_API_KEY="" rag-api-test &
sleep 3
curl -sf http://localhost:8080/health
kill %1
```

Expected: `docker build` succeeds (confirms the new `dockerContext`/`COPY` layout actually works, not just the YAML syntax); the container starts and `/health` returns `{"status": "ok"}` even with a deliberately-broken `DATABASE_URL` and no API keys, since `spend_guard` init and the `hr_policy` index build both fail gracefully per Task 5/7's lazy-resource design rather than crashing the process — this is a live, local proof of spec §4.4's graceful-degradation requirement, not just a unit test of it.

- [ ] **Step 10: Update `.env.example`**

Add this section to `.env.example`, after the existing "Model gateway request tuning" block:

```
# -----------------------------------------------------------------------------
# hr_policy domain (apps/api) -- requires a real Postgres for spend_guard
# -----------------------------------------------------------------------------
# Any reachable Postgres 14+ works locally (a local install, or Docker).
# In production this is the provisioned Supabase connection string.
DATABASE_URL=postgresql://localhost:5432/gateway_dev

# hr_policy uses Gemini for embeddings in production since Ollama isn't
# deployable on Render's free tier -- override the platform-wide default
# (EMBED_PROVIDER=ollama above) for this domain's deployment.
# EMBED_PROVIDER=gemini
# LLM_PROVIDER_SECONDARY=gemini
```

- [ ] **Step 11: Final full-repo verification**

Run from the repo root:

```bash
cd apps/api && .venv/bin/pytest tests/ -v && .venv/bin/ruff check . && .venv/bin/black --check . && .venv/bin/mypy src && cd ../..
cd packages/model_gateway && .venv/bin/pytest tests/ -v && .venv/bin/ruff check . && .venv/bin/black --check . && .venv/bin/mypy src && cd ../..
cd packages/spend_guard && .venv/bin/pytest tests/ -v && .venv/bin/ruff check . && .venv/bin/black --check . && .venv/bin/mypy src && cd ../..
```

Expected: everything green across all three packages/apps.

- [ ] **Step 12: Commit**

```bash
git add apps/api/pyproject.toml packages/model_gateway/src/model_gateway/py.typed packages/spend_guard/src/spend_guard/py.typed .github/workflows/ci.yml apps/api/Dockerfile render.yaml .dockerignore .env.example
git rm apps/api/.dockerignore
git commit -m "chore: wire apps/api deps, strict mypy, CI Postgres service, and monorepo Docker build context"
```

---

## Deployment Tasks (controller-executed, gated on explicit user confirmation)

Tasks 9 and 10 are **not** dispatched to an SDD subagent. They involve live OAuth against a real Supabase account and manual Render dashboard configuration — actions that need direct user participation and cannot run inside a non-interactive subagent. The controller (main session) executes these directly, after Tasks 1-8 are merged to `main` with CI green, and only after the user explicitly confirms each step, per this project's established pattern (no push to shared infrastructure without confirmation).

### Task 9: Provision Supabase Postgres

1. User authenticates the Supabase MCP connector (`mcp__claude_ai_Supabase__authenticate`).
2. Controller provisions a new Supabase project/database via the connector.
3. Controller runs `spend_guard.schema.apply_schema()` against the new database's connection string (e.g. via a short throwaway Python script using `asyncpg.connect` + `apply_schema`, mirroring `packages/spend_guard/tests/conftest.py`'s `_apply_schema()`).
4. Controller verifies all three tables (`budget_ledger`, `circuit_breaker_state`, `global_breaker_state`) exist via a direct query.
5. Controller reports the connection string's presence (never its value) back to the user and confirms before proceeding to Task 10.

### Task 10: Configure Render and verify the live deployment

1. User (or controller, with explicit confirmation) sets `DATABASE_URL` (from Task 9), `GROQ_API_KEY`, `GEMINI_API_KEY` as secret env vars in Render's dashboard for the `rag-portfolio-api` service.
2. Trigger a deploy (push to `main` after Task 8 merges, or a manual deploy trigger).
3. Controller verifies: `curl` against the live `/health` endpoint; `curl` a real question against `/api/v1/hr_policy/ask` and confirm a cited answer comes back; confirm the other 4 domains' `/status` scaffolds are still reachable.
4. **Live demonstration of spec §7's success criteria**: temporarily set `SPEND_GUARD_DAILY_CAP_USD=0` in Render's env vars (or issue enough real requests to exhaust the small default cap), redeploy, `curl` `/ask` again, and confirm a `503` with the specific "Daily budget for hr_policy has been reached" message comes back — then restore the real cap value and redeploy again. This is the literal, live proof of the master spec's Week 2 exit criterion.

---

## Self-Review Notes

(Completed by the plan's author before handing off — recorded here per the writing-plans skill's self-review requirement.)

- **Spec coverage:** §4.1 (module layout) → Tasks 2-4, 6. §4.2 (`estimate_precheck_cost`) → Task 1. §4.3 (`Chunk`) → Task 2. §4.4 (graceful degradation, `LazyResource`/`resolve_lazy`) → Task 5, wired in Task 7. §4.5 (request flow) → Task 6, with the added `record_failure` on embed failure and the double `record_success` call (embed + complete) as a deliberate completeness improvement beyond the spec's literal text — both real provider costs get recorded, not just the completion's. §4.6 (infra) → Task 8 (deps/CI/Docker/render.yaml/env) + Task 9-10 (provisioning/deploy). §5 (error handling) → Task 6's exact status codes/messages. §6 (testing strategy) → every task's own test step, using real local Postgres for `spend_guard` and `httpx.MockTransport` for `model_gateway`, matching the spec exactly. §7 (success criteria) → Task 10, Step 4.
- **Real infra gaps found and fixed during planning, not left for an implementer to discover:** (1) `py.typed` markers needed on `model_gateway`/`spend_guard` for `apps/api`'s strict mypy to type-check them as installed packages rather than `Any` — verified empirically in a throwaway venv before writing Task 8. (2) Render's `rootDir` scopes the Docker build context, which breaks `COPY`ing sibling `packages/*` directories — verified against Render's Blueprint spec docs that `dockerContext: .` at repo root is the documented fix, and that `apps/api/.dockerignore` becomes dead code once the context root moves (replaced with a repo-root `.dockerignore`). (3) `hatchling`'s default Python-module packaging doesn't ship the non-`.py` `hr_policy.md` data file in a built wheel without an explicit `force-include` entry — added in Task 8, Step 9 exists specifically to verify this rather than assume it.
- **Placeholder scan:** no "TBD"/"add appropriate handling"/"similar to Task N" language anywhere in the task steps; every code block is complete, runnable code.
- **Type consistency check:** `Chunk(header, text, vector)` (Task 2) is used identically in Task 3 (`RetrievalIndex`, `build_hr_policy_index`), Task 4 (`build_prompt`), and Task 6 (`router.py`'s `Source` construction from `chunk.header`/`chunk.text`). `LazyResource[T]`/`resolve_lazy` (Task 5) is used identically for both `SpendGuard` (Task 5's `get_spend_guard`) and `RetrievalIndex` (Task 6's `get_hr_policy_index`, Task 7's lifespan). `ProviderError.attempted_providers` (Task 1) is consumed identically for both `embed()` and `complete()` failures in Task 6's `_last_attempted_provider` helper. `SpendDecision` member names (`BLOCK_BUDGET_EXCEEDED`, `BLOCK_GLOBAL_BREAKER`, `BLOCK_VELOCITY_SPIKE`) match the current `packages/spend_guard/src/spend_guard/guard.py` exactly (post the Week 2b fix round's rename from `BLOCK_CIRCUIT_BREAKER`) — verified by reading the live file, not assumed from the spec text.
