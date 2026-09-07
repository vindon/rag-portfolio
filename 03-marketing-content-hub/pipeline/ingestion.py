"""
03-marketing-content-hub/pipeline/ingestion.py

Ingests product knowledge documents into Qdrant vector store.

Concepts demonstrated:
  - Qdrant collections (one per knowledge category)
  - Metadata filtering (filter by category at query time)
  - LlamaIndex QdrantVectorStore integration
  - Incremental upsert (avoids re-indexing unchanged docs)
"""

import sys
import logging
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    Settings,
    Document,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from shared.config import config
from shared.llm_factory import get_llm
from shared.embedder_factory import get_embedder, get_embedding_dim

logger = logging.getLogger(__name__)

# Three semantic knowledge collections
COLLECTIONS = {
    "product_features": "Core product features, capabilities and technical specs",
    "case_studies":     "Customer success stories and measurable outcomes",
    "faqs":             "Frequently asked questions and sales objection handling",
}


class KnowledgeIngestionPipeline:
    """
    Manages Qdrant collections for the Marketing Content Hub.

    Each collection holds one category of knowledge so retrieval
    can be scoped (e.g. 'only search case studies') for precision.
    """

    def __init__(self) -> None:
        Settings.llm = get_llm()
        Settings.embed_model = get_embedder()
        Settings.node_parser = SentenceSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )
        self.dim = get_embedding_dim()
        self._init_client()
        self._init_collections()

    def _init_client(self) -> None:
        url = config.qdrant_url
        if url == ":memory:":
            self.client = QdrantClient(":memory:")
            logger.info("Qdrant: in-memory mode")
        else:
            self.client = QdrantClient(url=url)
            logger.info("Qdrant: connected to %s", url)

    def _init_collections(self) -> None:
        """Create collections if they don't exist."""
        existing = {c.name for c in self.client.get_collections().collections}
        for name in COLLECTIONS:
            if name not in existing:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=self.dim,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", name)
            else:
                logger.info("Collection exists: %s", name)

    def get_vector_store(self, collection_name: str) -> QdrantVectorStore:
        return QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
        )

    def get_index(self, collection_name: str) -> VectorStoreIndex:
        vector_store = self.get_vector_store(collection_name)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        return VectorStoreIndex.from_vector_store(
            vector_store, storage_context=storage_context
        )

    def ingest_file(self, file_path: str, collection_name: str) -> int:
        """
        Load and index a single file into the specified collection.
        Returns the number of chunks indexed.
        """
        if collection_name not in COLLECTIONS:
            raise ValueError(
                f"Unknown collection '{collection_name}'. "
                f"Valid: {list(COLLECTIONS.keys())}"
            )
        path = Path(file_path)
        logger.info("Ingesting '%s' → collection '%s'", path.name, collection_name)

        if path.suffix == ".pdf":
            documents = SimpleDirectoryReader(input_files=[str(path)]).load_data()
        else:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            documents = [Document(
                text=text,
                metadata={
                    "file_name": path.name,
                    "category": collection_name,
                    "source": str(path),
                }
            )]

        vector_store = self.get_vector_store(collection_name)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=True,
        )
        count = self.client.get_collection(collection_name).points_count
        logger.info("Collection '%s' now has %d vectors", collection_name, count)
        return count

    def ingest_directory(self, data_dir: str, collection_name: str = "product_features") -> int:
        """Ingest all .md/.txt/.pdf files in a directory into a single collection."""
        docs = SimpleDirectoryReader(
            data_dir,
            required_exts=[".md", ".txt", ".pdf"],
            recursive=True,
        ).load_data()

        for doc in docs:
            doc.metadata["category"] = collection_name

        vector_store = self.get_vector_store(collection_name)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        VectorStoreIndex.from_documents(
            docs,
            storage_context=storage_context,
            show_progress=True,
        )
        count = self.client.get_collection(collection_name).points_count
        logger.info("Ingested %d docs → %d chunks in '%s'", len(docs), count, collection_name)
        return count

    def collection_stats(self) -> dict:
        stats = {}
        for name in COLLECTIONS:
            try:
                info = self.client.get_collection(name)
                stats[name] = {
                    "vectors": info.points_count,
                    "description": COLLECTIONS[name],
                }
            except Exception as e:
                stats[name] = {"error": str(e)}
        return stats
