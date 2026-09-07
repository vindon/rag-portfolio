"""
05-it-helpdesk-agent/tools/weaviate_rag.py

Weaviate Embedded knowledge-base tool for the IT Helpdesk agent.

Concepts demonstrated:
  - Weaviate v4 client API (weaviate-client>=4.5.0)
  - Embedded mode (no Docker — process auto-starts)
  - Manual vector insertion using Ollama embeddings
  - Near-vector ANN search at query time
  - Graceful fallback to in-memory dict store if Weaviate fails
"""

import sys
import os
import logging
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shared.config import config
from shared.embedder_factory import get_embedding_fn

logger = logging.getLogger(__name__)

COLLECTION_NAME = "ITDoc"


class WeaviateKBTool:
    """
    Manages the Weaviate knowledge base for IT documentation.

    On first use, documents are ingested from data/it_docs.md.
    Subsequent calls reuse the persistent embedded instance.

    Falls back to a simple TF-IDF-style in-memory search
    if Weaviate is unavailable.
    """

    _client = None
    _ready = False
    _fallback_docs: List[Dict] = []

    def __init__(self) -> None:
        if not WeaviateKBTool._ready:
            self._init()

    def _init(self) -> None:
        try:
            self._connect()
            self._ensure_collection()
            self._ingest_if_empty()
            WeaviateKBTool._ready = True
        except Exception as e:
            logger.warning(
                "Weaviate initialisation failed (%s) — falling back to in-memory search", e
            )
            self._load_fallback_docs()

    def _connect(self) -> None:
        import weaviate

        weaviate_url = config.weaviate_url
        if weaviate_url:
            WeaviateKBTool._client = weaviate.connect_to_local(
                host=weaviate_url.replace("http://", "").split(":")[0],
                port=int(weaviate_url.split(":")[-1]) if ":" in weaviate_url else 8080,
            )
            logger.info("Weaviate: connected to %s", weaviate_url)
        else:
            WeaviateKBTool._client = weaviate.connect_to_embedded()
            logger.info("Weaviate: embedded mode started")

    def _ensure_collection(self) -> None:
        import weaviate.classes.config as wc

        client = WeaviateKBTool._client
        if not client.collections.exists(COLLECTION_NAME):
            client.collections.create(
                name=COLLECTION_NAME,
                vectorizer_config=wc.Configure.Vectorizer.none(),
                properties=[
                    wc.Property(name="content",  data_type=wc.DataType.TEXT),
                    wc.Property(name="source",   data_type=wc.DataType.TEXT),
                    wc.Property(name="category", data_type=wc.DataType.TEXT),
                ],
            )
            logger.info("Created Weaviate collection: %s", COLLECTION_NAME)

    def _ingest_if_empty(self) -> None:
        client = WeaviateKBTool._client
        collection = client.collections.get(COLLECTION_NAME)
        count = collection.aggregate.over_all(total_count=True).total_count
        if count and count > 0:
            logger.info("Weaviate collection has %d objects — skipping ingest", count)
            return

        # Load IT docs
        data_file = Path(__file__).parent.parent / "data" / "it_docs.md"
        if not data_file.exists():
            logger.warning("IT docs not found at %s", data_file)
            return

        chunks = self._chunk_document(data_file.read_text(encoding="utf-8"))
        embed_fn = get_embedding_fn()

        logger.info("Ingesting %d chunks into Weaviate...", len(chunks))
        with collection.batch.dynamic() as batch:
            for chunk in chunks:
                try:
                    vector = embed_fn(chunk["content"])
                    batch.add_object(properties=chunk, vector=vector)
                except Exception as e:
                    logger.warning("Failed to embed chunk: %s", e)

        logger.info("Weaviate ingest complete — %d chunks", len(chunks))

    def _chunk_document(self, text: str, chunk_size: int = 400) -> List[Dict]:
        """Simple paragraph-based chunking for the IT docs."""
        sections = text.split("\n## ")
        chunks = []
        for section in sections:
            if not section.strip():
                continue
            lines = section.strip().split("\n")
            title = lines[0].strip("# ").strip()
            body = " ".join(lines[1:]).strip()

            # Further split long sections into ~400 char chunks
            words = body.split()
            current, current_len = [], 0
            for word in words:
                current.append(word)
                current_len += len(word) + 1
                if current_len >= chunk_size:
                    chunks.append({
                        "content":  " ".join(current),
                        "source":   title,
                        "category": self._classify(title),
                    })
                    current, current_len = [], 0
            if current:
                chunks.append({
                    "content":  " ".join(current),
                    "source":   title,
                    "category": self._classify(title),
                })
        return chunks

    def _classify(self, title: str) -> str:
        title_lower = title.lower()
        if "password" in title_lower or "mfa" in title_lower or "auth" in title_lower:
            return "password"
        if "vpn" in title_lower:
            return "vpn"
        if "software" in title_lower or "install" in title_lower or "slack" in title_lower:
            return "software"
        if "hardware" in title_lower or "equipment" in title_lower:
            return "hardware"
        if "network" in title_lower or "wifi" in title_lower or "ethernet" in title_lower:
            return "network"
        return "other"

    def _load_fallback_docs(self) -> None:
        """Load IT docs into memory for keyword fallback."""
        data_file = Path(__file__).parent.parent / "data" / "it_docs.md"
        if data_file.exists():
            WeaviateKBTool._fallback_docs = self._chunk_document(
                data_file.read_text(encoding="utf-8")
            )
            logger.info("Loaded %d fallback docs", len(WeaviateKBTool._fallback_docs))

    def search(self, query: str, top_k: int = 4) -> List[Dict]:
        """Search the knowledge base — Weaviate vector search or keyword fallback."""
        if WeaviateKBTool._ready and WeaviateKBTool._client:
            return self._weaviate_search(query, top_k)
        return self._fallback_search(query, top_k)

    def _weaviate_search(self, query: str, top_k: int) -> List[Dict]:
        try:
            embed_fn = get_embedding_fn()
            vector = embed_fn(query)
            collection = WeaviateKBTool._client.collections.get(COLLECTION_NAME)
            results = collection.query.near_vector(
                near_vector=vector,
                limit=top_k,
                return_properties=["content", "source", "category"],
            )
            return [
                {
                    "content":  obj.properties.get("content", ""),
                    "source":   obj.properties.get("source", "IT Docs"),
                    "category": obj.properties.get("category", "other"),
                    "score":    round(obj.metadata.distance or 0, 4) if obj.metadata else 0,
                }
                for obj in results.objects
            ]
        except Exception as e:
            logger.warning("Weaviate search failed: %s — using keyword fallback", e)
            return self._fallback_search(query, top_k)

    def _fallback_search(self, query: str, top_k: int) -> List[Dict]:
        """Naive keyword overlap search when Weaviate is unavailable."""
        query_words = set(query.lower().split())
        scored = []
        for doc in WeaviateKBTool._fallback_docs:
            doc_words = set(doc["content"].lower().split())
            score = len(query_words & doc_words)
            if score > 0:
                scored.append((score, doc))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [doc for _, doc in scored[:top_k]]

    def close(self) -> None:
        if WeaviateKBTool._client:
            try:
                WeaviateKBTool._client.close()
            except Exception:
                pass
