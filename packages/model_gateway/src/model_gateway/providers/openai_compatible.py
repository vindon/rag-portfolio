from __future__ import annotations

import time
from urllib.parse import urlparse

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
        # Parse base_url to extract scheme and netloc only (ignore any path component)
        parsed = urlparse(base_url.rstrip("/"))
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
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
