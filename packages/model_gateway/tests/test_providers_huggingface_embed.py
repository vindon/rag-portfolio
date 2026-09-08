from __future__ import annotations

import httpx
import pytest

from model_gateway.providers.huggingface_embed import HuggingFaceEmbeddingProvider
from model_gateway.types import ProviderAPIError


@pytest.mark.anyio
async def test_embed_returns_one_vector_per_input() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/models/BAAI/bge-small-en-v1.5"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=[[0.1, 0.2], [0.3, 0.4]])

    provider = HuggingFaceEmbeddingProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.embed(["a", "b"], model="BAAI/bge-small-en-v1.5")
    assert result.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert result.provider == "huggingface"


@pytest.mark.anyio
async def test_embed_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="model loading")

    provider = HuggingFaceEmbeddingProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderAPIError):
        await provider.embed(["a"], model="BAAI/bge-small-en-v1.5")
