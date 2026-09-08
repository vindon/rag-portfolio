from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def call_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 2,
    base_delay_seconds: float = 0.5,
) -> T:
    attempt = 0
    while True:
        try:
            return await fn()
        except Exception:
            if attempt >= max_retries:
                raise
            await asyncio.sleep(base_delay_seconds * (2**attempt))
            attempt += 1
