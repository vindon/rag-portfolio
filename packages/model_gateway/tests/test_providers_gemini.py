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
    assert body["contents"] == [{"role": "user", "parts": [{"text": "What is the leave policy?"}]}]

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
