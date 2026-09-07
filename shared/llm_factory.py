"""
shared/llm_factory.py
Returns the configured LLM for LlamaIndex (Projects 01–04)
or LangChain/LangGraph (Project 05).
Switch providers with LLM_PROVIDER in .env — no code changes.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_llm(temperature: float = 0.1, streaming: bool = False) -> Any:
    """
    Return a LlamaIndex-compatible LLM instance.
    Used by Projects 01, 02, 03, 04.
    """
    from shared.config import config
    provider = config.llm_provider
    logger.info("Initialising LlamaIndex LLM: provider=%s", provider)

    if provider == "groq":
        from llama_index.llms.groq import Groq
        return Groq(
            model=config.groq_model,
            api_key=config.groq_api_key,
            temperature=temperature,
        )

    if provider == "gemini":
        from llama_index.llms.gemini import Gemini
        return Gemini(
            model=config.gemini_model,
            api_key=config.gemini_api_key,
            temperature=temperature,
        )

    if provider == "ollama":
        from llama_index.llms.ollama import Ollama
        return Ollama(
            model=config.ollama_llm_model,
            base_url=config.ollama_base_url,
            temperature=temperature,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. "
        "Valid options: groq | gemini | ollama"
    )


def get_langchain_llm(temperature: float = 0) -> Any:
    """
    Return a LangChain-compatible LLM instance.
    Used by Project 05 (LangGraph multi-agent).
    """
    from shared.config import config
    provider = config.llm_provider
    logger.info("Initialising LangChain LLM: provider=%s", provider)

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=config.groq_model,
            groq_api_key=config.groq_api_key,
            temperature=temperature,
        )

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=config.gemini_model.replace("models/", ""),
            google_api_key=config.gemini_api_key,
            temperature=temperature,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=config.ollama_llm_model,
            base_url=config.ollama_base_url,
            temperature=temperature,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. "
        "Valid options: groq | gemini | ollama"
    )
