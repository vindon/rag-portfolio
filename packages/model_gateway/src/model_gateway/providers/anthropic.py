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
