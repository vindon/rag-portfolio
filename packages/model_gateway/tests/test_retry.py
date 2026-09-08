from __future__ import annotations

import pytest

from model_gateway.retry import call_with_retry


@pytest.mark.anyio
async def test_call_with_retry_returns_on_first_success() -> None:
    calls = {"count": 0}

    async def fn() -> str:
        calls["count"] += 1
        return "ok"

    result = await call_with_retry(fn, max_retries=2, base_delay_seconds=0.0)
    assert result == "ok"
    assert calls["count"] == 1


@pytest.mark.anyio
async def test_call_with_retry_succeeds_after_transient_failures() -> None:
    calls = {"count": 0}

    async def fn() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("transient")
        return "ok"

    result = await call_with_retry(fn, max_retries=2, base_delay_seconds=0.0)
    assert result == "ok"
    assert calls["count"] == 3


@pytest.mark.anyio
async def test_call_with_retry_raises_after_exhausting_retries() -> None:
    calls = {"count": 0}

    async def fn() -> str:
        calls["count"] += 1
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError, match="permanent"):
        await call_with_retry(fn, max_retries=2, base_delay_seconds=0.0)
    assert calls["count"] == 3
