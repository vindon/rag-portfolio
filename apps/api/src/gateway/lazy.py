from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from fastapi import HTTPException

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class LazyResource(Generic[T]):
    value: T | None = None
    build_error: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def resolve_lazy(
    resource: LazyResource[T], build: Callable[[], Awaitable[T]], *, error_detail: str
) -> T:
    if resource.value is not None:
        return resource.value
    async with resource.lock:
        if resource.value is not None:
            return resource.value
        try:
            built = await build()
        except Exception as exc:
            resource.build_error = str(exc)
            logger.critical("gateway.lazy_rebuild_failed error=%s", exc)
            raise HTTPException(status_code=503, detail=error_detail) from exc
        resource.value = built
        resource.build_error = None
        return built
