from __future__ import annotations

from model_gateway.pricing import estimate_cost


def test_estimate_cost_known_model() -> None:
    cost = estimate_cost(
        provider="groq",
        model="llama-3.3-70b-versatile",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert cost == 0.59 + 0.79


def test_estimate_cost_prices_cached_tokens_at_cached_rate() -> None:
    cost = estimate_cost(
        provider="anthropic",
        model="claude-3-5-haiku-latest",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_input_tokens=1_000_000,
    )
    assert cost == 0.08


def test_estimate_cost_unknown_model_returns_zero() -> None:
    cost = estimate_cost(provider="unknown", model="unknown", input_tokens=100, output_tokens=100)
    assert cost == 0.0


def test_estimate_cost_free_local_provider() -> None:
    cost = estimate_cost(
        provider="ollama", model="llama3.2", input_tokens=1_000_000, output_tokens=1_000_000
    )
    assert cost == 0.0
