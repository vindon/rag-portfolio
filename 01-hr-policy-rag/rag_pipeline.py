"""
01-hr-policy-rag/rag_pipeline.py

Core RAG pipeline for the HR Policy Q&A Bot.

Concepts demonstrated:
  - Document loading with SimpleDirectoryReader
  - Chunking with SentenceSplitter (chunk_size, chunk_overlap)
  - Embedding with Ollama (nomic-embed-text)
  - In-memory VectorStoreIndex (FAISS-style, no infra needed)
  - Custom prompt template for domain-specific tone
  - Source attribution with scored retrievals
"""

import sys
import logging
from pathlib import Path

# Allow `from shared.x import y` when running from this sub-directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    Settings,
    PromptTemplate,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import get_response_synthesizer

from shared.config import config
from shared.llm_factory import get_llm
from shared.embedder_factory import get_embedder
from shared.utils import format_sources, timeit

logger = logging.getLogger(__name__)

# ── Custom HR prompt ──────────────────────────────────────────────────────────
HR_PROMPT = PromptTemplate(
    "You are a knowledgeable HR assistant for Acme Corp employees. "
    "Answer the question accurately and concisely based only on the provided "
    "HR policy documents. If the policy is silent on a topic, say so clearly "
    "rather than guessing. Always cite the specific policy section number.\n\n"
    "Policy context:\n"
    "─────────────────────────────────────────\n"
    "{context_str}\n"
    "─────────────────────────────────────────\n\n"
    "Employee question: {query_str}\n\n"
    "Answer (include section reference):"
)

REFINE_PROMPT = PromptTemplate(
    "You are refining an HR policy answer. The original answer is below. "
    "If the additional context provides new information, improve the answer. "
    "Otherwise keep the original answer.\n\n"
    "Original answer:\n{existing_answer}\n\n"
    "Additional context:\n{context_msg}\n\n"
    "Refined answer:"
)


class HRPolicyRAG:
    """
    End-to-end RAG pipeline for querying HR policy documents.

    Architecture:
        SimpleDirectoryReader → SentenceSplitter → OllamaEmbedding
        → VectorStoreIndex → VectorIndexRetriever → RetrieverQueryEngine
    """

    def __init__(
        self,
        data_dir: str = "data",
        chunk_size: int = None,
        chunk_overlap: int = None,
        top_k: int = None,
    ) -> None:
        self.data_dir = data_dir
        self.chunk_size = chunk_size or config.chunk_size
        self.chunk_overlap = chunk_overlap or config.chunk_overlap
        self.top_k = top_k or config.retrieval_top_k
        self.index: VectorStoreIndex | None = None
        self.query_engine: RetrieverQueryEngine | None = None
        self._build()

    @timeit
    def _build(self) -> None:
        """Load documents, chunk, embed, and build the in-memory index."""
        # 1. Global LlamaIndex settings
        Settings.llm = get_llm()
        Settings.embed_model = get_embedder()
        Settings.node_parser = SentenceSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        # 2. Load documents
        logger.info("Loading documents from '%s'", self.data_dir)
        documents = SimpleDirectoryReader(
            self.data_dir,
            required_exts=[".md", ".txt", ".pdf"],
            recursive=True,
        ).load_data()
        logger.info("Loaded %d document(s)", len(documents))

        # 3. Build in-memory vector index (FAISS under the hood)
        logger.info(
            "Building VectorStoreIndex (chunk_size=%d, chunk_overlap=%d)...",
            self.chunk_size,
            self.chunk_overlap,
        )
        self.index = VectorStoreIndex.from_documents(
            documents,
            show_progress=True,
        )

        # 4. Assemble query engine
        retriever = VectorIndexRetriever(
            index=self.index,
            similarity_top_k=self.top_k,
        )
        synthesizer = get_response_synthesizer(
            text_qa_template=HR_PROMPT,
            refine_template=REFINE_PROMPT,
            streaming=False,
        )
        self.query_engine = RetrieverQueryEngine(
            retriever=retriever,
            response_synthesizer=synthesizer,
        )
        logger.info("HR Policy RAG pipeline ready ✓")

    def query(self, question: str) -> dict:
        """
        Query the HR knowledge base.

        Returns:
            {
              "answer":  str,
              "sources": [{"file": str, "page": str, "score": float, "excerpt": str}]
            }
        """
        if not self.query_engine:
            raise RuntimeError("Pipeline not initialised. Call _build() first.")

        logger.info("Query: %s", question)
        response = self.query_engine.query(question)

        return {
            "answer": str(response).strip(),
            "sources": format_sources(response.source_nodes),
        }
