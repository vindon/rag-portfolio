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
        assert request.url.path == "/v1/messages"
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
