from __future__ import annotations

import re
from dataclasses import dataclass, field


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
