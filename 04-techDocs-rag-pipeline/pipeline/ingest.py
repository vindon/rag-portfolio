"""
04-techDocs-rag-pipeline/pipeline/ingest.py

Document ingestion pipeline for the Technical Docs Assistant.
Uses Milvus Lite (embedded, no Docker) as the vector store.

Concepts demonstrated:
  - Milvus Lite embedded vector store
  - SentenceSplitter with custom chunk parameters
  - Metadata enrichment per document chunk
  - Document deduplication via hash
  - BM25 index serialisation alongside vector index
"""

import sys
import logging
import json
import pickle
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    Settings,
    Document,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode
from llama_index.vector_stores.milvus import MilvusVectorStore

from shared.config import config
from shared.llm_factory import get_llm
from shared.embedder_factory import get_embedder, get_embedding_dim
from shared.utils import hash_file, timeit

logger = logging.getLogger(__name__)

BM25_CACHE_PATH = ".bm25_index.pkl"
NODE_CACHE_PATH = ".nodes_cache.pkl"


class DocumentIngestionPipeline:
    """
    Ingests technical documentation into Milvus Lite.
    Also serialises raw nodes for BM25 sparse retrieval.

    Architecture:
        SimpleDirectoryReader → SentenceSplitter → OllamaEmbedding
        → MilvusVectorStore (dense) + BM25Index (sparse, on disk)
    """

    def __init__(self, milvus_uri: str = None, collection: str = "tech_docs") -> None:
        Settings.llm = get_llm()
        Settings.embed_model = get_embedder()

        self.milvus_uri = milvus_uri or config.milvus_uri
        self.collection = collection
        self.dim = get_embedding_dim()
        self.index: VectorStoreIndex | None = None
        self.nodes: List[TextNode] = []

    @timeit
    def ingest(
        self,
        data_dir: str,
        chunk_size: int = None,
        chunk_overlap: int = None,
        overwrite: bool = False,
    ) -> Tuple[VectorStoreIndex, List[TextNode]]:
        """
        Load documents, chunk, embed, and store in Milvus.

        Returns (VectorStoreIndex, list_of_nodes) for building
        the BM25 sparse retriever.
        """
        chunk_size = chunk_size or config.chunk_size
        chunk_overlap = chunk_overlap or config.chunk_overlap

        splitter = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        logger.info("Loading docs from '%s'", data_dir)
        raw_documents = SimpleDirectoryReader(
            data_dir,
            required_exts=[".md", ".txt", ".pdf"],
            recursive=True,
        ).load_data()
        logger.info("Loaded %d document(s)", len(raw_documents))

        # Enrich metadata
        for doc in raw_documents:
            doc.metadata["source_hash"] = hash_file(
                doc.metadata.get("file_path", "")
            ) if doc.metadata.get("file_path") else "unknown"
            doc.metadata["project"] = "tech_docs"

        # Parse into nodes
        self.nodes = splitter.get_nodes_from_documents(raw_documents)
        logger.info("Split into %d chunks (size=%d, overlap=%d)",
                    len(self.nodes), chunk_size, chunk_overlap)

        # Milvus Lite vector store
        vector_store = MilvusVectorStore(
            uri=self.milvus_uri,
            collection_name=self.collection,
            dim=self.dim,
            overwrite=overwrite,
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        logger.info("Building Milvus index (uri=%s, collection=%s)…",
                    self.milvus_uri, self.collection)
        self.index = VectorStoreIndex(
            self.nodes,
            storage_context=storage_context,
            show_progress=True,
        )

        # Cache nodes to disk for BM25 retriever
        with open(NODE_CACHE_PATH, "wb") as f:
            pickle.dump(self.nodes, f)
        logger.info("Node cache written to %s", NODE_CACHE_PATH)

        logger.info("Ingestion complete — %d chunks in Milvus", len(self.nodes))
        return self.index, self.nodes

    def load_existing(self) -> Tuple[VectorStoreIndex, List[TextNode]]:
        """
        Load an existing Milvus index without re-ingesting.
        Raises FileNotFoundError if Milvus DB or node cache not found.
        """
        if not Path(self.milvus_uri).exists() and self.milvus_uri != ":memory:":
            raise FileNotFoundError(
                f"Milvus database not found at '{self.milvus_uri}'. "
                "Run ingestion first."
            )

        Settings.embed_model = get_embedder()
        Settings.llm = get_llm()

        vector_store = MilvusVectorStore(
            uri=self.milvus_uri,
            collection_name=self.collection,
            dim=self.dim,
            overwrite=False,
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        self.index = VectorStoreIndex.from_vector_store(
            vector_store,
            storage_context=storage_context,
        )

        if Path(NODE_CACHE_PATH).exists():
            with open(NODE_CACHE_PATH, "rb") as f:
                self.nodes = pickle.load(f)
            logger.info("Loaded %d cached nodes for BM25", len(self.nodes))
        else:
            logger.warning("Node cache not found — BM25 will be unavailable")

        return self.index, self.nodes

    def get_or_ingest(self, data_dir: str) -> Tuple[VectorStoreIndex, List[TextNode]]:
        """Convenience: load existing index or ingest if not found."""
        try:
            return self.load_existing()
        except FileNotFoundError:
            logger.info("No existing index found, ingesting from '%s'", data_dir)
            return self.ingest(data_dir, overwrite=True)
