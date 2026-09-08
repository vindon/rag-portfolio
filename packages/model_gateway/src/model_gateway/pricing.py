from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import yaml

_PRICING_PATH = Path(__file__).parent / "pricing.yaml"


class ModelPrice(TypedDict):
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float


def _load_pricing_table(path: Path = _PRICING_PATH) -> dict[str, dict[str, ModelPrice]]:
    with path.open() as f:
        raw = yaml.safe_load(f)
    return raw or {}


_PRICING_TABLE = _load_pricing_table()


def estimate_cost(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    price = _PRICING_TABLE.get(provider, {}).get(model)
    if price is None:
        return 0.0
    fresh_input_tokens = max(input_tokens - cached_input_tokens, 0)
    return (
        fresh_input_tokens * price["input_per_million"] / 1_000_000
        + cached_input_tokens * price["cached_input_per_million"] / 1_000_000
        + output_tokens * price["output_per_million"] / 1_000_000
    )
