from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    usage: Usage
    latency_ms: float


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model: str
    usage: Usage
    latency_ms: float


class ProviderError(Exception):
    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class ProviderAPIError(ProviderError):
    def __init__(self, provider: str, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(provider, f"HTTP {status_code}: {message}")
