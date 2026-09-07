"""
02-contract-review-chat/rag_engine.py

RAG engine powering the Contract Review Assistant.

Concepts demonstrated:
  - Multi-document support (upload multiple contracts)
  - ChatMemoryBuffer for conversational context across turns
  - CondensePlusContextChatEngine for follow-up question handling
  - Streaming token generation
  - Per-session index caching
"""

import sys
import logging
from pathlib import Path
from typing import Generator, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    Settings,
    Document,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.chat_engine import CondensePlusContextChatEngine
from llama_index.core.retrievers import VectorIndexRetriever

from shared.config import config
from shared.llm_factory import get_llm
from shared.embedder_factory import get_embedder
from shared.utils import format_sources, timeit

logger = logging.getLogger(__name__)

CONTRACT_SYSTEM_PROMPT = """You are an expert contract analyst assisting legal and procurement teams.
Your role is to:
- Extract and explain key contract terms clearly and accurately
- Flag risks, obligations, and important deadlines
- Highlight clauses that may need legal review
- Answer follow-up questions using the full conversation context
- Always ground your answers in the contract text provided
- If a term is ambiguous, flag it rather than interpreting speculatively

Use precise legal language where appropriate, but explain technical terms in plain English."""


class ContractReviewEngine:
    """
    Multi-document, multi-turn RAG engine for contract review.

    Architecture:
        PDF/text upload → SentenceSplitter → OllamaEmbedding
        → VectorStoreIndex → VectorIndexRetriever
        → CondensePlusContextChatEngine (with ChatMemoryBuffer)
    """

    def __init__(self) -> None:
        self._configure_settings()
        self.index: VectorStoreIndex | None = None
        self.chat_engine: CondensePlusContextChatEngine | None = None
        self.loaded_files: List[str] = []

    def _configure_settings(self) -> None:
        Settings.llm = get_llm(streaming=True)
        Settings.embed_model = get_embedder()
        Settings.node_parser = SentenceSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )

    @timeit
    def load_documents(self, file_paths: List[str]) -> int:
        """
        Load one or more contract files, build/update the index.
        Returns the number of chunks indexed.
        """
        documents = []
        for fp in file_paths:
            path = Path(fp)
            if not path.exists():
                logger.warning("File not found: %s", fp)
                continue

            if path.suffix == ".pdf":
                docs = SimpleDirectoryReader(
                    input_files=[str(path)]
                ).load_data()
            else:
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                docs = [Document(text=content, metadata={"file_name": path.name})]

            documents.extend(docs)
            self.loaded_files.append(path.name)
            logger.info("Loaded: %s (%d chars)", path.name, sum(len(d.text) for d in docs))

        if not documents:
            raise ValueError("No valid documents found in the provided paths.")

        self.index = VectorStoreIndex.from_documents(
            documents,
            show_progress=True,
        )
        self._build_chat_engine()
        total_nodes = len(self.index.docstore.docs)
        logger.info("Index built: %d chunks from %d file(s)", total_nodes, len(file_paths))
        return total_nodes

    def _build_chat_engine(self) -> None:
        """Assemble the multi-turn chat engine with memory."""
        retriever = VectorIndexRetriever(
            index=self.index,
            similarity_top_k=config.retrieval_top_k,
        )
        memory = ChatMemoryBuffer.from_defaults(token_limit=4096)
        self.chat_engine = CondensePlusContextChatEngine.from_defaults(
            retriever=retriever,
            memory=memory,
            system_prompt=CONTRACT_SYSTEM_PROMPT,
            verbose=False,
        )
        logger.info("Chat engine ready with ChatMemoryBuffer (4096 token limit)")

    def chat_stream(self, message: str) -> Generator[str, None, None]:
        """
        Send a message and stream the response token by token.
        Yields individual text tokens for Streamlit st.write_stream().
        """
        if not self.chat_engine:
            yield "⚠️ No documents loaded. Please upload a contract first."
            return

        response = self.chat_engine.stream_chat(message)
        for token in response.response_gen:
            yield token

    def get_sources(self, message: str) -> List[dict]:
        """Return source nodes for the last query (non-streaming)."""
        if not self.chat_engine:
            return []
        response = self.chat_engine.chat(message)
        return format_sources(getattr(response, "source_nodes", []))

    def reset_memory(self) -> None:
        """Clear conversation history while keeping the document index."""
        if self.chat_engine:
            self.chat_engine.reset()
            logger.info("Chat memory cleared")

    def clear(self) -> None:
        """Full reset — clears index, memory, and loaded files."""
        self.index = None
        self.chat_engine = None
        self.loaded_files = []
        logger.info("Engine fully reset")

    @property
    def is_ready(self) -> bool:
        return self.chat_engine is not None
