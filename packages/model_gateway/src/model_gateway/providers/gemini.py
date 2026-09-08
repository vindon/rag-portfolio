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
        model = model.removeprefix("models/")
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
        model = model.removeprefix("models/")
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
