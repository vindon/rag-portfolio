from __future__ import annotations

import httpx
import pytest

from model_gateway.providers.openai_compatible import OpenAICompatibleProvider
from model_gateway.types import ChatMessage, ProviderAPIError, Role


@pytest.mark.anyio
async def test_complete_returns_parsed_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/openai/v1/chat/completions"
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
    result = await provider.complete(
        [ChatMessage(role=Role.USER, content="hi")], model="gpt-4o-mini"
    )
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
        assert request.url.path == "/v1/embeddings"
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
