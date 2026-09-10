from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from model_gateway.gateway import ModelGateway
from model_gateway.settings import GatewaySettings, ProviderConfig

from gateway.domains.hr_policy.retrieval import (
    Chunk,
    RetrievalIndex,
    build_hr_policy_index,
    chunk_markdown,
)

_SAMPLE_MD = """\
# Acme Corp Policy Manual

## 1. Annual Leave Policy

### 1.1 Entitlement

Full-time employees accrue 20 days of paid annual leave per year.

Leave is accrued monthly and can be taken after the first 90 days.

### 1.2 Leave Carry-Over

Up to 5 unused days may be carried into the next calendar year.

## 2. Remote Work Policy

Employees may work remotely up to 3 days per week with manager approval.
"""


def test_chunk_markdown_tracks_nearest_header_per_paragraph() -> None:
    chunks = chunk_markdown(_SAMPLE_MD)

    assert all(isinstance(c, Chunk) for c in chunks)
    assert [c.header for c in chunks] == [
        "1.1 Entitlement",
        "1.1 Entitlement",
        "1.2 Leave Carry-Over",
        "2. Remote Work Policy",
    ]


def test_chunk_markdown_splits_on_blank_lines_within_a_section() -> None:
    chunks = chunk_markdown(_SAMPLE_MD)

    entitlement_chunks = [c for c in chunks if c.header == "1.1 Entitlement"]
    assert len(entitlement_chunks) == 2
    assert "20 days" in entitlement_chunks[0].text
    assert "90 days" in entitlement_chunks[1].text


def test_chunk_markdown_strips_leading_hashes_from_header() -> None:
    chunks = chunk_markdown(_SAMPLE_MD)

    assert all(not c.header.startswith("#") for c in chunks)


def test_chunk_markdown_skips_empty_sections() -> None:
    md = "# Title\n\n## Empty Section\n\n## Non-Empty Section\n\nSome text here.\n"

    chunks = chunk_markdown(md)

    assert len(chunks) == 1
    assert chunks[0].header == "Non-Empty Section"
    assert chunks[0].text == "Some text here."


def test_chunk_defaults_to_empty_vector() -> None:
    chunks = chunk_markdown("# H\n\nBody text.\n")

    assert chunks[0].vector == []


def test_retrieval_index_search_ranks_by_cosine_similarity() -> None:
    chunks = [
        Chunk(header="A", text="a", vector=[1.0, 0.0]),
        Chunk(header="B", text="b", vector=[0.0, 1.0]),
        Chunk(header="C", text="c", vector=[0.9, 0.1]),
    ]
    index = RetrievalIndex(chunks)

    results = index.search([1.0, 0.0], k=2)

    assert [c.header for c, _score in results] == ["A", "C"]
    assert results[0][1] == pytest.approx(1.0)


def test_retrieval_index_search_respects_k() -> None:
    chunks = [Chunk(header=str(i), text=str(i), vector=[float(i), 1.0]) for i in range(10)]
    index = RetrievalIndex(chunks)

    results = index.search([5.0, 1.0], k=3)

    assert len(results) == 3


def test_retrieval_index_search_handles_zero_vector_without_crashing() -> None:
    chunks = [Chunk(header="A", text="a", vector=[0.0, 0.0])]
    index = RetrievalIndex(chunks)

    results = index.search([1.0, 0.0], k=1)

    assert results[0][1] == 0.0


@pytest.mark.anyio
async def test_build_hr_policy_index_embeds_every_chunk_and_attaches_vectors(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "hr_policy.md"
    data_path.write_text("# Title\n\n## Section One\n\nFirst paragraph.\n\nSecond paragraph.\n")

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        import json

        texts = json.loads(body)["input"]
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": [float(i), 0.0]} for i in range(len(texts))]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = {"fake": ProviderConfig("fake", "https://fake.example/v1", "k", "embed-model")}
    settings = GatewaySettings(
        llm_primary="",
        llm_secondary="",
        llm_local="",
        embed_primary="fake",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        retry_base_delay_seconds=0.001,
        llm_providers={},
        embed_providers=providers,
    )
    gateway = ModelGateway(settings, client=client)

    index = await build_hr_policy_index(gateway, data_path=data_path)

    results = index.search([0.0, 0.0], k=2)
    assert len(results) == 2
    assert all(len(chunk.vector) == 2 for chunk, _score in results)


def test_chunk_markdown_parses_the_real_hr_policy_doc() -> None:
    real_path = Path(__file__).parent.parent / "src/gateway/domains/hr_policy/data/hr_policy.md"

    chunks = chunk_markdown(real_path.read_text())

    assert len(chunks) > 10
    assert any("leave" in c.text.lower() for c in chunks)
