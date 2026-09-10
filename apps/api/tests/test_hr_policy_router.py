from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
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


def _build_app(*, gateway: ModelGateway, spend_guard: SpendGuard, index: RetrievalIndex) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_model_gateway] = lambda: gateway
    app.dependency_overrides[get_spend_guard] = lambda: spend_guard
    app.dependency_overrides[get_hr_policy_index] = lambda: index
    return app


async def _post(app: FastAPI, path: str, json: dict[str, object]) -> httpx.Response:
    # NOTE: uses httpx.AsyncClient + ASGITransport rather than
    # fastapi.testclient.TestClient -- see discrepancy note in
    # task-6-report.md. TestClient's `with TestClient(app) as client:` spins
    # up a *separate thread with its own event loop* (via
    # anyio.from_thread.start_blocking_portal) to run the ASGI app. The real
    # asyncpg connection pool built by the `real_spend_guard`/
    # `zero_budget_spend_guard` fixtures is bound to the outer anyio test's
    # event loop, so calling into it from TestClient's separate loop raised
    # `asyncpg.exceptions.InterfaceError: cannot perform operation: another
    # operation is in progress`. Driving the ASGI app directly on the test's
    # own event loop avoids the cross-loop asyncpg usage entirely.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, json=json)


def _fake_gateway(
    transport_handler: Callable[[httpx.Request], httpx.Response],
) -> ModelGateway:
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport_handler))
    providers = {
        "groq": ProviderConfig(
            "groq", "https://api.groq.com/openai/v1", "k", "llama-3.3-70b-versatile"
        ),
    }
    # NOTE: uses an "openai"-named embed provider (routed through
    # OpenAICompatibleProvider) rather than "gemini" -- see discrepancy note
    # in task-6-report.md. GeminiProvider issues per-text POSTs to
    # `:embedContent` and parses a `{"embedding": {"values": [...]}}` body,
    # which doesn't match this mock's OpenAI-shaped `/embeddings` response.
    embed_providers = {
        "openai": ProviderConfig(
            "openai", "https://fake.example/v1", "k", "text-embedding-3-small"
        ),
    }
    settings = GatewaySettings(
        llm_primary="groq",
        llm_secondary="",
        llm_local="",
        embed_primary="openai",
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

    response = await _post(app, "/api/v1/hr_policy/ask", {"question": "How much leave?"})

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

    response = await _post(app, "/api/v1/hr_policy/ask", {"question": "How much leave?"})

    assert response.status_code == 503
    assert "budget" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_ask_falls_back_to_secondary_provider_and_reports_it(
    real_spend_guard: SpendGuard,
) -> None:
    call_count = {"groq": 0, "secondary_chat": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "embeddings" in url:
            return _embed_response(1)
        if "groq" in url or "primary" in url:
            call_count["groq"] += 1
            return httpx.Response(500, text="boom")
        call_count["secondary_chat"] += 1
        return _chat_response("fallback answer")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    # NOTE: secondary LLM provider is named "openai" (OpenAICompatibleProvider)
    # rather than "gemini" -- see discrepancy note in task-6-report.md.
    # GeminiProvider's real request/response shape (generateContent /
    # candidates[0].content.parts) doesn't match this mock's OpenAI-shaped
    # chat-completions response, so using "gemini" here would make BOTH
    # providers in the chain fail rather than exercising the fallback path.
    providers = {
        "groq": ProviderConfig(
            "groq", "https://api.groq.com/openai/v1", "k", "llama-3.3-70b-versatile"
        ),
        "openai": ProviderConfig("openai", "https://fake.example/v1beta", "k", "gpt-4o-mini"),
    }
    embed_providers = {
        "openai": ProviderConfig(
            "openai", "https://fake.example/v1", "k", "text-embedding-3-small"
        ),
    }
    settings = GatewaySettings(
        llm_primary="groq",
        llm_secondary="openai",
        llm_local="",
        embed_primary="openai",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        retry_base_delay_seconds=0.001,
        llm_providers=providers,
        embed_providers=embed_providers,
    )
    gateway = ModelGateway(settings, client=client)
    app = _build_app(gateway=gateway, spend_guard=real_spend_guard, index=_INDEX)

    response = await _post(app, "/api/v1/hr_policy/ask", {"question": "q"})

    assert response.status_code == 200
    assert response.json()["provider_used"] == "openai"
    assert call_count["groq"] == 1
    assert call_count["secondary_chat"] == 1


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

    response = await _post(app, "/api/v1/hr_policy/ask", {"question": "q"})

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
    # 1 failure, threshold 3 -- provider should still be considered available.
    assert await real_spend_guard.is_provider_available(provider="groq") is True


@pytest.mark.anyio
async def test_precheck_never_returns_downgrade_to_local_for_hr_policy(
    zero_budget_spend_guard: SpendGuard,
) -> None:
    decision = await zero_budget_spend_guard.precheck(0.01, has_local_fallback=False)

    assert decision != SpendDecision.DOWNGRADE_TO_LOCAL
    assert decision == SpendDecision.BLOCK_BUDGET_EXCEEDED
