"""
03-marketing-content-hub/pipeline/generation.py

Retrieves relevant context from Qdrant, then generates
content using the appropriate template for the requested content type.

Concepts demonstrated:
  - Template routing pattern (one LLM, many prompts)
  - Multi-collection RAG query with collection selection
  - Streaming generation
  - Metadata-filtered retrieval
"""

import sys
import logging
from pathlib import Path
from typing import Generator, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.llms import LLM

from shared.llm_factory import get_llm
from shared.utils import truncate
from .ingestion import KnowledgeIngestionPipeline
from .templates import ContentType, TEMPLATES, Template

logger = logging.getLogger(__name__)

# Which collections to search per content type
COLLECTION_MAP = {
    ContentType.LINKEDIN_POST:       ["product_features", "case_studies"],
    ContentType.BLOG_ARTICLE:        ["product_features", "case_studies", "faqs"],
    ContentType.DEMO_SCRIPT:         ["product_features", "case_studies"],
    ContentType.EMAIL_CAMPAIGN:      ["case_studies", "faqs"],
    ContentType.CASE_STUDY_SNIPPET:  ["case_studies"],
}


class ContentGenerationEngine:
    """
    Generates marketing content by:
      1. Retrieving relevant context from Qdrant (by collection)
      2. Building a prompt using the template for the requested content type
      3. Streaming the LLM response

    The routing logic (collection selection, template selection) is
    what makes this a 'content hub' rather than a generic RAG app.
    """

    def __init__(self, pipeline: KnowledgeIngestionPipeline) -> None:
        self.pipeline = pipeline
        self.llm: LLM = get_llm(streaming=True)

    def _retrieve_context(
        self,
        topic: str,
        content_type: ContentType,
        top_k: int = 5,
    ) -> str:
        """
        Query the relevant Qdrant collections and merge the results
        into a single context string.
        """
        collections = COLLECTION_MAP.get(content_type, ["product_features"])
        all_excerpts: List[str] = []

        for collection_name in collections:
            try:
                index: VectorStoreIndex = self.pipeline.get_index(collection_name)
                retriever = VectorIndexRetriever(index=index, similarity_top_k=top_k)
                nodes = retriever.retrieve(topic)
                for node in nodes:
                    source = node.metadata.get("file_name", "knowledge base")
                    excerpt = truncate(node.text, 600)
                    all_excerpts.append(f"[Source: {source}]\n{excerpt}")
                logger.debug(
                    "Retrieved %d chunks from '%s' for topic: %s",
                    len(nodes), collection_name, topic
                )
            except Exception as e:
                logger.warning("Could not query collection '%s': %s", collection_name, e)

        if not all_excerpts:
            return "No relevant context found in the knowledge base."

        return "\n\n---\n\n".join(all_excerpts)

    def generate_stream(
        self,
        topic: str,
        content_type: ContentType,
    ) -> Generator[str, None, None]:
        """
        Retrieve context and stream content generation token by token.
        Suitable for Streamlit's st.write_stream().
        """
        template: Template = TEMPLATES[content_type]
        logger.info(
            "Generating %s for topic: '%s'", content_type.value, topic
        )

        # Step 1: RAG retrieval
        context = self._retrieve_context(topic, content_type)

        # Step 2: Build prompt
        user_prompt = template.user_template.format(
            topic=topic,
            context=context,
        )

        # Step 3: Stream LLM completion
        from llama_index.core.llms import ChatMessage, MessageRole
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=template.system_prompt),
            ChatMessage(role=MessageRole.USER, content=user_prompt),
        ]

        response = self.llm.stream_chat(messages)
        for delta in response:
            yield delta.delta

    def generate(self, topic: str, content_type: ContentType) -> dict:
        """
        Non-streaming version. Returns content + metadata.
        Useful for batch generation or testing.
        """
        template: Template = TEMPLATES[content_type]
        context = self._retrieve_context(topic, content_type)

        user_prompt = template.user_template.format(topic=topic, context=context)

        from llama_index.core.llms import ChatMessage, MessageRole
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=template.system_prompt),
            ChatMessage(role=MessageRole.USER, content=user_prompt),
        ]
        response = self.llm.chat(messages)

        return {
            "content": response.message.content,
            "content_type": content_type.value,
            "topic": topic,
            "template_name": template.name,
            "expected_length": template.expected_length,
            "tone": template.tone,
            "context_used": context[:500] + "...",
        }
