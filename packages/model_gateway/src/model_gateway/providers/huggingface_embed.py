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
