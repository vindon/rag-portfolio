"""
shared/embedder_factory.py
Returns the configured embedding model for:
  - LlamaIndex (Projects 01–04)  → get_embedder()
  - Raw vector generation         → get_embedding_fn() returns a plain callable
Switch providers with EMBED_PROVIDER in .env — no code changes.
"""

import logging
from typing import Any, Callable, List

logger = logging.getLogger(__name__)


def get_embedder() -> Any:
    """
    Return a LlamaIndex-compatible embedding model.
    Used by Projects 01, 02, 03, 04.
    """
    from shared.config import config
    provider = config.embed_provider
    logger.info("Initialising embedder: provider=%s", provider)

    if provider == "ollama":
        from llama_index.embeddings.ollama import OllamaEmbedding
        return OllamaEmbedding(
            model_name=config.ollama_embed_model,
            base_url=config.ollama_base_url,
        )

    if provider == "gemini":
        from llama_index.embeddings.gemini import GeminiEmbedding
        return GeminiEmbedding(
            model_name=config.gemini_embed_model,
            api_key=config.gemini_api_key,
        )

    if provider == "huggingface":
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        return HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")

    raise ValueError(
        f"Unknown EMBED_PROVIDER '{provider}'. "
        "Valid options: ollama | gemini | huggingface"
    )


def get_embedding_fn() -> Callable[[str], List[float]]:
    """
    Return a plain callable: text -> vector.
    Used by Project 05 (Weaviate raw inserts / queries).
    """
    from shared.config import config
    provider = config.embed_provider

    if provider == "ollama":
        import requests

        def embed(text: str) -> List[float]:
            resp = requests.post(
                f"{config.ollama_base_url}/api/embeddings",
                json={"model": config.ollama_embed_model, "prompt": text},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["embedding"]

        return embed

    if provider == "gemini":
        import google.generativeai as genai

        genai.configure(api_key=config.gemini_api_key)

        def embed(text: str) -> List[float]:
            result = genai.embed_content(
                model=config.gemini_embed_model,
                content=text,
                task_type="retrieval_document",
            )
            return result["embedding"]

        return embed

    if provider == "huggingface":
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("BAAI/bge-small-en-v1.5")

        def embed(text: str) -> List[float]:
            return _model.encode(text).tolist()

        return embed

    raise ValueError(f"Unknown EMBED_PROVIDER '{provider}'")


def get_embedding_dim() -> int:
    """Return the vector dimension for the configured embedding model."""
    from shared.config import config
    dims = {
        # Ollama models
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        # Gemini
        "models/text-embedding-004": 768,
        # HuggingFace
        "BAAI/bge-small-en-v1.5": 384,
    }
    model = (
        config.ollama_embed_model if config.embed_provider == "ollama"
        else config.gemini_embed_model if config.embed_provider == "gemini"
        else "BAAI/bge-small-en-v1.5"
    )
    return dims.get(model, 768)
