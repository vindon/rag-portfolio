from __future__ import annotations

from gateway.domains.hr_policy.retrieval import Chunk, chunk_markdown

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
