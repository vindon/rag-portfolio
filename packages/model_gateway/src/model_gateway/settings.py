from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class GatewaySettings:
    llm_primary: str
    llm_secondary: str
    llm_local: str
    embed_primary: str
    embed_secondary: str
    timeout_seconds: float
    max_retries: int
    retry_base_delay_seconds: float = 0.5
    llm_providers: dict[str, ProviderConfig] = field(default_factory=dict)
    embed_providers: dict[str, ProviderConfig] = field(default_factory=dict)

    def llm_fallback_chain(self) -> list[str]:
        chain = [self.llm_primary]
        for name in (self.llm_secondary, self.llm_local):
            if name and name not in chain:
                chain.append(name)
        return [name for name in chain if name in self.llm_providers]

    def embed_fallback_chain(self) -> list[str]:
        chain = [self.embed_primary]
        if self.embed_secondary and self.embed_secondary not in chain:
            chain.append(self.embed_secondary)
        return [name for name in chain if name in self.embed_providers]


def load_settings(env: dict[str, str] | None = None) -> GatewaySettings:
    source = env if env is not None else dict(os.environ)

    def get(key: str, default: str = "") -> str:
        return source.get(key, default)

    ollama_base = get("OLLAMA_BASE_URL", "http://localhost:11434")

    llm_providers = {
        "groq": ProviderConfig(
            "groq",
            "https://api.groq.com/openai/v1",
            get("GROQ_API_KEY"),
            get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        ),
        "openai": ProviderConfig(
            "openai",
            "https://api.openai.com/v1",
            get("OPENAI_API_KEY"),
            get("OPENAI_MODEL", "gpt-4o-mini"),
        ),
        "mistral": ProviderConfig(
            "mistral",
            "https://api.mistral.ai/v1",
            get("MISTRAL_API_KEY"),
            get("MISTRAL_MODEL", "mistral-small-latest"),
        ),
        "cohere": ProviderConfig(
            "cohere",
            "https://api.cohere.com/compatibility/v1",
            get("COHERE_API_KEY"),
            get("COHERE_MODEL", "command-r"),
        ),
        "huggingface": ProviderConfig(
            "huggingface",
            "https://router.huggingface.co/v1",
            get("HUGGINGFACE_API_KEY"),
            get("HUGGINGFACE_MODEL", "meta-llama/Llama-3.1-8B-Instruct"),
        ),
        "ollama": ProviderConfig(
            "ollama", f"{ollama_base}/v1", "", get("OLLAMA_LLM_MODEL", "llama3.2")
        ),
        "anthropic": ProviderConfig(
            "anthropic",
            "https://api.anthropic.com/v1",
            get("ANTHROPIC_API_KEY"),
            get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
        ),
        "gemini": ProviderConfig(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            get("GEMINI_API_KEY"),
            get("GEMINI_MODEL", "gemini-2.0-flash"),
        ),
    }
    embed_providers = {
        "ollama": ProviderConfig(
            "ollama", f"{ollama_base}/v1", "", get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        ),
        "gemini": ProviderConfig(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            get("GEMINI_API_KEY"),
            get("GEMINI_EMBED_MODEL", "text-embedding-004"),
        ),
        "huggingface": ProviderConfig(
            "huggingface",
            "https://api-inference.huggingface.co/models",
            get("HUGGINGFACE_API_KEY"),
            get("HUGGINGFACE_EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
        ),
        "openai": ProviderConfig(
            "openai",
            "https://api.openai.com/v1",
            get("OPENAI_API_KEY"),
            get("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        ),
    }

    return GatewaySettings(
        llm_primary=get("LLM_PROVIDER", "groq"),
        llm_secondary=get("LLM_PROVIDER_SECONDARY", ""),
        llm_local=get("LLM_PROVIDER_LOCAL", "ollama"),
        embed_primary=get("EMBED_PROVIDER", "ollama"),
        embed_secondary=get("EMBED_PROVIDER_SECONDARY", ""),
        timeout_seconds=float(get("MODEL_GATEWAY_TIMEOUT_SECONDS", "30")),
        max_retries=int(get("MODEL_GATEWAY_MAX_RETRIES", "2")),
        retry_base_delay_seconds=float(get("MODEL_GATEWAY_RETRY_BASE_DELAY_SECONDS", "0.5")),
        llm_providers=llm_providers,
        embed_providers=embed_providers,
    )
