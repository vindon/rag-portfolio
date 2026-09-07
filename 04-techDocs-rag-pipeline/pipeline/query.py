"""
04-techDocs-rag-pipeline/pipeline/query.py

Hybrid retrieval engine combining:
  - Dense retrieval: Milvus vector similarity (Ollama embeddings)
  - Sparse retrieval: BM25 keyword matching
  - Fusion: Reciprocal Rank Fusion (RRF)
  - Re-ranking: Cross-encoder (ms-marco-MiniLM)

Concepts demonstrated:
  - QueryFusionRetriever (RRF hybrid search)
  - BM25Retriever for keyword-based sparse retrieval
  - SentenceTransformerRerank post-processing
  - RetrieverQueryEngine with custom prompt
  - Configurable retrieval parameters
"""

import sys
import logging
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from llama_index.core import VectorStoreIndex, Settings, PromptTemplate
from llama_index.core.retrievers import VectorIndexRetriever, QueryFusionRetriever
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.schema import TextNode
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.postprocessor.sbert_rerank import SentenceTransformerRerank

from shared.config import config
from shared.utils import format_sources

logger = logging.getLogger(__name__)

TECH_DOCS_PROMPT = PromptTemplate(
    "You are a technical documentation assistant helping engineers and developers.\n"
    "Answer the question accurately using ONLY the provided documentation context.\n"
    "If the answer isn't in the docs, say 'This isn't covered in the current documentation.'\n"
    "Include code examples when relevant. Be precise and technical.\n\n"
    "Documentation context:\n"
    "═══════════════════════════════════════════\n"
    "{context_str}\n"
    "═══════════════════════════════════════════\n\n"
    "Question: {query_str}\n\n"
    "Answer:"
)

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class HybridQueryEngine:
    """
    Production-grade hybrid retrieval for technical documentation.

    Pipeline:
        query
          ├─ Dense retriever (Milvus cosine similarity, top-k=8)
          ├─ BM25 retriever (keyword matching, top-k=8)
          └─ QueryFusionRetriever (RRF merge, top-k=6)
               └─ SentenceTransformerRerank (cross-encoder, top-n=3)
                    └─ ResponseSynthesizer → final answer
    """

    def __init__(
        self,
        index: VectorStoreIndex,
        nodes: List[TextNode],
        dense_top_k: int = 8,
        sparse_top_k: int = 8,
        fusion_top_k: int = 6,
        rerank_top_n: int = 3,
        use_reranker: bool = True,
    ) -> None:
        self.dense_top_k = dense_top_k
        self.sparse_top_k = sparse_top_k
        self.fusion_top_k = fusion_top_k
        self.rerank_top_n = rerank_top_n
        self.use_reranker = use_reranker
        self.query_engine = self._build(index, nodes)

    def _build(
        self,
        index: VectorStoreIndex,
        nodes: List[TextNode],
    ) -> RetrieverQueryEngine:
        # 1. Dense retriever — Milvus ANN search
        dense_retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=self.dense_top_k,
        )
        logger.info("Dense retriever ready (top_k=%d)", self.dense_top_k)

        # 2. Sparse retriever — BM25 over all nodes
        bm25_retriever = BM25Retriever.from_defaults(
            nodes=nodes,
            similarity_top_k=self.sparse_top_k,
        )
        logger.info("BM25 retriever ready (top_k=%d, nodes=%d)",
                    self.sparse_top_k, len(nodes))

        # 3. Fusion: Reciprocal Rank Fusion merges dense + sparse results
        fusion_retriever = QueryFusionRetriever(
            retrievers=[dense_retriever, bm25_retriever],
            similarity_top_k=self.fusion_top_k,
            num_queries=1,         # no query expansion (keeps latency low)
            mode="reciprocal_rerank",
            use_async=False,
            verbose=False,
        )
        logger.info("Hybrid retriever ready (RRF fusion, top_k=%d)", self.fusion_top_k)

        # 4. Re-ranker — cross-encoder scores actual query-chunk relevance
        node_postprocessors = []
        if self.use_reranker:
            reranker = SentenceTransformerRerank(
                model=RERANKER_MODEL,
                top_n=self.rerank_top_n,
            )
            node_postprocessors.append(reranker)
            logger.info(
                "Reranker ready: %s (top_n=%d)", RERANKER_MODEL, self.rerank_top_n
            )

        # 5. Response synthesizer with tech docs prompt
        synthesizer = get_response_synthesizer(
            text_qa_template=TECH_DOCS_PROMPT,
            streaming=False,
        )

        engine = RetrieverQueryEngine(
            retriever=fusion_retriever,
            response_synthesizer=synthesizer,
            node_postprocessors=node_postprocessors,
        )
        logger.info("HybridQueryEngine ready ✓")
        return engine

    def query(self, question: str) -> dict:
        """
        Run hybrid retrieval + re-ranking + synthesis.

        Returns:
          {
            "answer": str,
            "sources": List[dict],
            "retrieval_method": "dense+bm25+rrf+rerank"
          }
        """
        logger.info("Query: %s", question)
        response = self.query_engine.query(question)
        return {
            "answer": str(response).strip(),
            "sources": format_sources(response.source_nodes),
            "retrieval_method": (
                "Dense (Milvus) + BM25 + RRF + "
                + (f"CrossEncoder ({RERANKER_MODEL})" if self.use_reranker else "No reranker")
            ),
        }
