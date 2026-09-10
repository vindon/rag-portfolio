from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from model_gateway.gateway import ModelGateway


@dataclass(frozen=True)
class Chunk:
    header: str
    text: str
    vector: list[float] = field(default_factory=list)


_HEADER_RE = re.compile(r"^#{1,6}\s+(.*)$")


def chunk_markdown(markdown_text: str) -> list[Chunk]:
    """Split a markdown document into (header, paragraph) chunks.

    Tracks the most recently seen heading (any level 1-6) as the citation
    label for every paragraph that follows it, until the next heading.
    Blank lines separate paragraphs within a section. A section with no body
    text before the next heading (or end of document) produces no chunk.
    """
    current_header = ""
    chunks: list[Chunk] = []
    paragraph_lines: list[str] = []

    def flush() -> None:
        text = "\n".join(paragraph_lines).strip()
        if text:
            chunks.append(Chunk(header=current_header, text=text))
        paragraph_lines.clear()

    for line in markdown_text.splitlines():
        header_match = _HEADER_RE.match(line)
        if header_match:
            flush()
            current_header = header_match.group(1).strip()
            continue
        if line.strip() == "":
            flush()
            continue
        paragraph_lines.append(line)
    flush()
    return chunks


_DATA_PATH = Path(__file__).parent / "data" / "hr_policy.md"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a = np.array(a, dtype=float)
    vec_b = np.array(b, dtype=float)
    norm_a = float(np.linalg.norm(vec_a))
    norm_b = float(np.linalg.norm(vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


class RetrievalIndex:
    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks

    def search(self, query_vector: list[float], k: int) -> list[tuple[Chunk, float]]:
        scored = [(chunk, _cosine_similarity(query_vector, chunk.vector)) for chunk in self._chunks]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


async def build_hr_policy_index(
    gateway: ModelGateway, *, data_path: Path = _DATA_PATH
) -> RetrievalIndex:
    raw_chunks = chunk_markdown(data_path.read_text())
    if not raw_chunks:
        raise ValueError(f"no chunks parsed from {data_path}")
    outcome = await gateway.embed([chunk.text for chunk in raw_chunks])
    embedded = [
        replace(chunk, vector=vector)
        for chunk, vector in zip(raw_chunks, outcome.result.vectors, strict=True)
    ]
    return RetrievalIndex(embedded)
