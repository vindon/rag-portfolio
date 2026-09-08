from __future__ import annotations

from typing import Protocol

from model_gateway.types import ChatMessage, CompletionResult, EmbeddingResult


class ChatProvider(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> CompletionResult: ...


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str], *, model: str) -> EmbeddingResult: ...
