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
        "groq": ProviderConfig(
            "groq", "https://primary.example/v1", "k", "llama-3.3-70b-versatile"
        ),
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
    try:
        with pytest.raises(ProviderError):
            await gateway.complete([ChatMessage(role=Role.USER, content="hi")])
    finally:
        await gateway.aclose()


@pytest.mark.anyio
async def test_gateway_without_injected_client_owns_and_closes_it() -> None:
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

    assert gateway._owns_client is True
    assert gateway._client.is_closed is False

    await gateway.aclose()

    assert gateway._client.is_closed is True


@pytest.mark.anyio
async def test_gateway_with_injected_client_does_not_close_it() -> None:
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
    injected_client = httpx.AsyncClient()
    gateway = ModelGateway(settings, client=injected_client)

    assert gateway._owns_client is False

    await gateway.aclose()

    assert injected_client.is_closed is False
    await injected_client.aclose()


@pytest.mark.anyio
async def test_complete_routes_anthropic_provider_to_messages_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert "x-api-key" in request.headers
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {
        "anthropic": ProviderConfig(
            "anthropic", "https://api.anthropic.com/v1", "k", "claude-3-5-haiku-latest"
        ),
    }
    settings = GatewaySettings(
        llm_primary="anthropic",
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
    assert outcome.attempted_providers == ["anthropic"]


@pytest.mark.anyio
async def test_complete_routes_gemini_provider_to_generate_content_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "generateContent" in str(request.url)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {
        "gemini": ProviderConfig(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "k",
            "gemini-2.0-flash",
        ),
    }
    settings = GatewaySettings(
        llm_primary="gemini",
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
    assert outcome.attempted_providers == ["gemini"]


@pytest.mark.anyio
async def test_embed_returns_result_from_huggingface_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/models/BAAI/bge-small-en-v1.5"
        return httpx.Response(200, json=[[0.1, 0.2], [0.3, 0.4]])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {
        "huggingface": ProviderConfig(
            "huggingface",
            "https://api-inference.huggingface.co/models",
            "k",
            "BAAI/bge-small-en-v1.5",
        ),
    }
    settings = GatewaySettings(
        llm_primary="",
        llm_secondary="",
        llm_local="",
        embed_primary="huggingface",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        retry_base_delay_seconds=0.001,
        llm_providers={},
        embed_providers=providers,
    )
    gateway = ModelGateway(settings, client=client)

    result = await gateway.embed(["a", "b"])

    assert result.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert result.provider == "huggingface"


@pytest.mark.anyio
async def test_embed_falls_back_to_secondary_on_primary_failure() -> None:
    call_count = {"primary": 0, "secondary": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "primary" in str(request.url):
            call_count["primary"] += 1
            return httpx.Response(500, text="boom")
        call_count["secondary"] += 1
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5, 0.6]}]})

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

    result = await gateway.embed(["hi"])

    assert result.vectors == [[0.5, 0.6]]
    assert call_count["primary"] == 1
    assert call_count["secondary"] == 1
