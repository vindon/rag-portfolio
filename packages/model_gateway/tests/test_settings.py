from __future__ import annotations

from model_gateway.settings import load_settings


def test_load_settings_defaults() -> None:
    settings = load_settings(env={})
    assert settings.llm_primary == "groq"
    assert settings.llm_local == "ollama"
    assert settings.embed_primary == "ollama"
    assert "groq" in settings.llm_providers
    assert "anthropic" in settings.llm_providers
    assert "gemini" in settings.embed_providers
    assert "huggingface" in settings.embed_providers


def test_load_settings_reads_env_overrides() -> None:
    settings = load_settings(
        env={
            "LLM_PROVIDER": "openai",
            "LLM_PROVIDER_SECONDARY": "anthropic",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_MODEL": "gpt-4o",
        }
    )
    assert settings.llm_primary == "openai"
    assert settings.llm_secondary == "anthropic"
    assert settings.llm_providers["openai"].api_key == "sk-test"
    assert settings.llm_providers["openai"].model == "gpt-4o"


def test_llm_fallback_chain_dedupes_and_skips_unconfigured() -> None:
    settings = load_settings(
        env={
            "LLM_PROVIDER": "groq",
            "LLM_PROVIDER_SECONDARY": "groq",
            "LLM_PROVIDER_LOCAL": "ollama",
        }
    )
    assert settings.llm_fallback_chain() == ["groq", "ollama"]


def test_llm_fallback_chain_skips_local_when_equal_to_primary() -> None:
    settings = load_settings(env={"LLM_PROVIDER": "ollama", "LLM_PROVIDER_LOCAL": "ollama"})
    assert settings.llm_fallback_chain() == ["ollama"]


def test_embed_fallback_chain_empty_secondary_is_skipped() -> None:
    settings = load_settings(env={"EMBED_PROVIDER": "ollama", "EMBED_PROVIDER_SECONDARY": ""})
    assert settings.embed_fallback_chain() == ["ollama"]
