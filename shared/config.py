"""
shared/config.py
Centralised configuration for all five RAG projects.
All settings are read from environment variables (via .env).
Change providers by editing .env — no code changes needed.
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


@dataclass
class Config:
    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_provider: str          = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "groq"))
    groq_api_key: str          = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_model: str            = field(default_factory=lambda: os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
    gemini_api_key: str        = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str          = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "models/gemini-2.0-flash-exp"))
    ollama_llm_model: str      = field(default_factory=lambda: os.getenv("OLLAMA_LLM_MODEL", "llama3.2"))

    # ── Embeddings ────────────────────────────────────────────────────────────
    embed_provider: str        = field(default_factory=lambda: os.getenv("EMBED_PROVIDER", "ollama"))
    ollama_base_url: str       = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    ollama_embed_model: str    = field(default_factory=lambda: os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
    gemini_embed_model: str    = field(default_factory=lambda: os.getenv("GEMINI_EMBED_MODEL", "models/text-embedding-004"))

    # ── Vector DBs ────────────────────────────────────────────────────────────
    qdrant_url: str            = field(default_factory=lambda: os.getenv("QDRANT_URL", ":memory:"))
    milvus_uri: str            = field(default_factory=lambda: os.getenv("MILVUS_URI", "./milvus.db"))
    weaviate_url: Optional[str]= field(default_factory=lambda: os.getenv("WEAVIATE_URL") or None)

    # ── RAG Tuning ────────────────────────────────────────────────────────────
    chunk_size: int            = field(default_factory=lambda: int(os.getenv("CHUNK_SIZE", "512")))
    chunk_overlap: int         = field(default_factory=lambda: int(os.getenv("CHUNK_OVERLAP", "64")))
    retrieval_top_k: int       = field(default_factory=lambda: int(os.getenv("RETRIEVAL_TOP_K", "4")))

    # ── Google Calendar ───────────────────────────────────────────────────────
    google_credentials_path: str = field(default_factory=lambda: os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json"))
    google_token_path: str       = field(default_factory=lambda: os.getenv("GOOGLE_TOKEN_PATH", "token.json"))

    def validate(self) -> None:
        """Raise early if required keys are missing."""
        log = logging.getLogger(__name__)
        if self.llm_provider == "groq" and not self.groq_api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. Get a free key at https://console.groq.com "
                "or switch LLM_PROVIDER to 'gemini' or 'ollama' in your .env"
            )
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey"
            )
        if self.embed_provider == "ollama":
            log.info(
                "Embedding provider: Ollama (%s) at %s — "
                "make sure Ollama is running: ollama serve",
                self.ollama_embed_model, self.ollama_base_url
            )
        log.info(
            "Config loaded — LLM: %s/%s | Embed: %s/%s",
            self.llm_provider,
            self.groq_model if self.llm_provider == "groq" else self.gemini_model,
            self.embed_provider,
            self.ollama_embed_model if self.embed_provider == "ollama" else self.gemini_embed_model,
        )


config = Config()
