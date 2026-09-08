from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import httpx

from model_gateway.pricing import estimate_cost
from model_gateway.providers.anthropic import AnthropicProvider
from model_gateway.providers.base import ChatProvider, EmbeddingProvider
from model_gateway.providers.gemini import GeminiProvider
from model_gateway.providers.huggingface_embed import HuggingFaceEmbeddingProvider
from model_gateway.providers.openai_compatible import OpenAICompatibleProvider
from model_gateway.retry import call_with_retry
from model_gateway.settings import GatewaySettings, ProviderConfig, load_settings
from model_gateway.types import ChatMessage, CompletionResult, EmbeddingResult, ProviderError

logger = logging.getLogger(__name__)


def _build_llm_adapter(
    config: ProviderConfig, *, timeout: float, client: httpx.AsyncClient | None
) -> ChatProvider:
    if config.name == "anthropic":
        return AnthropicProvider(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout_seconds=timeout,
            client=client,
        )
    if config.name == "gemini":
        return GeminiProvider(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout_seconds=timeout,
            client=client,
        )
    return OpenAICompatibleProvider(
        provider_name=config.name,
        base_url=config.base_url,
        api_key=config.api_key,
        timeout_seconds=timeout,
        client=client,
    )


def _build_embed_adapter(
    config: ProviderConfig, *, timeout: float, client: httpx.AsyncClient | None
) -> EmbeddingProvider:
    if config.name == "gemini":
        return GeminiProvider(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout_seconds=timeout,
            client=client,
        )
    if config.name == "huggingface":
        return HuggingFaceEmbeddingProvider(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout_seconds=timeout,
            client=client,
        )
    return OpenAICompatibleProvider(
        provider_name=config.name,
        base_url=config.base_url,
        api_key=config.api_key,
        timeout_seconds=timeout,
        client=client,
    )


@dataclass
class ChatOutcome:
    result: CompletionResult
    estimated_cost_usd: float
    attempted_providers: list[str]


@dataclass
class EmbedOutcome:
    result: EmbeddingResult
    estimated_cost_usd: float
    attempted_providers: list[str]


class ModelGateway:
    def __init__(
        self,
        settings: GatewaySettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or load_settings()
        self._owns_client = client is None
        self._client: httpx.AsyncClient = client if client is not None else httpx.AsyncClient()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> ModelGateway:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> ChatOutcome:
        chain = self._settings.llm_fallback_chain()
        if not chain:
            raise ProviderError("model_gateway", "no LLM providers configured")

        attempted: list[str] = []
        last_error: Exception | None = None
        for provider_name in chain:
            attempted.append(provider_name)
            config = self._settings.llm_providers[provider_name]
            adapter = _build_llm_adapter(
                config, timeout=self._settings.timeout_seconds, client=self._client
            )
            request_id = str(uuid.uuid4())

            async def _call(
                a: ChatProvider = adapter, c: ProviderConfig = config
            ) -> CompletionResult:
                return await a.complete(
                    messages, model=c.model, temperature=temperature, max_tokens=max_tokens
                )

            try:
                result = await call_with_retry(
                    _call,
                    max_retries=self._settings.max_retries,
                    base_delay_seconds=self._settings.retry_base_delay_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "model_gateway.complete.failed request_id=%s provider=%s error=%s",
                    request_id,
                    provider_name,
                    exc,
                )
                last_error = exc
                continue

            cost = estimate_cost(
                provider=provider_name,
                model=config.model,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cached_input_tokens=result.usage.cached_input_tokens,
            )
            logger.info(
                "model_gateway.complete.success request_id=%s provider=%s model=%s "
                "input_tokens=%d output_tokens=%d cached_input_tokens=%d "
                "estimated_cost_usd=%.6f latency_ms=%.1f",
                request_id,
                provider_name,
                config.model,
                result.usage.input_tokens,
                result.usage.output_tokens,
                result.usage.cached_input_tokens,
                cost,
                result.latency_ms,
            )
            return ChatOutcome(
                result=result, estimated_cost_usd=cost, attempted_providers=attempted
            )

        raise ProviderError(
            "model_gateway", f"all providers in fallback chain failed: {attempted}"
        ) from last_error

    async def embed(self, texts: list[str]) -> EmbedOutcome:
        chain = self._settings.embed_fallback_chain()
        if not chain:
            raise ProviderError("model_gateway", "no embedding providers configured")

        attempted: list[str] = []
        last_error: Exception | None = None
        for provider_name in chain:
            attempted.append(provider_name)
            config = self._settings.embed_providers[provider_name]
            adapter = _build_embed_adapter(
                config, timeout=self._settings.timeout_seconds, client=self._client
            )

            async def _call(
                a: EmbeddingProvider = adapter, c: ProviderConfig = config
            ) -> EmbeddingResult:
                return await a.embed(texts, model=c.model)

            try:
                embed_result = await call_with_retry(
                    _call,
                    max_retries=self._settings.max_retries,
                    base_delay_seconds=self._settings.retry_base_delay_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "model_gateway.embed.failed provider=%s error=%s", provider_name, exc
                )
                last_error = exc
                continue

            cost = estimate_cost(
                provider=provider_name,
                model=config.model,
                input_tokens=embed_result.usage.input_tokens,
                output_tokens=embed_result.usage.output_tokens,
                cached_input_tokens=embed_result.usage.cached_input_tokens,
            )
            logger.info(
                "model_gateway.embed.success provider=%s model=%s input_tokens=%d "
                "estimated_cost_usd=%.6f latency_ms=%.1f",
                provider_name,
                config.model,
                embed_result.usage.input_tokens,
                cost,
                embed_result.latency_ms,
            )
            return EmbedOutcome(
                result=embed_result, estimated_cost_usd=cost, attempted_providers=attempted
            )

        raise ProviderError(
            "model_gateway", f"all embedding providers failed: {attempted}"
        ) from last_error
