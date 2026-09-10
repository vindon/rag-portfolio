from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request as StarletteRequest

from gateway.dependencies import get_model_gateway, get_spend_guard
from gateway.lazy import LazyResource, resolve_lazy


@pytest.mark.anyio
async def test_resolve_lazy_returns_cached_value_without_rebuilding() -> None:
    build_calls = {"count": 0}

    async def build() -> str:
        build_calls["count"] += 1
        return "built"

    resource: LazyResource[str] = LazyResource(value="cached")

    result = await resolve_lazy(resource, build, error_detail="nope")

    assert result == "cached"
    assert build_calls["count"] == 0


@pytest.mark.anyio
async def test_resolve_lazy_builds_and_caches_on_first_use() -> None:
    async def build() -> str:
        return "built"

    resource: LazyResource[str] = LazyResource()

    result = await resolve_lazy(resource, build, error_detail="nope")

    assert result == "built"
    assert resource.value == "built"
    assert resource.build_error is None


@pytest.mark.anyio
async def test_resolve_lazy_raises_503_and_records_error_on_build_failure() -> None:
    async def build() -> str:
        raise RuntimeError("boom")

    resource: LazyResource[str] = LazyResource()

    with pytest.raises(HTTPException) as exc_info:
        await resolve_lazy(resource, build, error_detail="unavailable")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "unavailable"
    assert resource.value is None
    assert resource.build_error == "boom"


@pytest.mark.anyio
async def test_resolve_lazy_recovers_after_a_prior_failed_attempt() -> None:
    attempt = {"count": 0}

    async def build() -> str:
        attempt["count"] += 1
        if attempt["count"] == 1:
            raise RuntimeError("first attempt fails")
        return "recovered"

    resource: LazyResource[str] = LazyResource()

    with pytest.raises(HTTPException):
        await resolve_lazy(resource, build, error_detail="unavailable")

    result = await resolve_lazy(resource, build, error_detail="unavailable")

    assert result == "recovered"
    assert resource.build_error is None


def test_get_model_gateway_reads_app_state() -> None:
    app = FastAPI()
    app.state.gateway = "fake-gateway-object"

    async def _check() -> None:
        request = StarletteRequest({"type": "http", "app": app})
        result = await get_model_gateway(request)
        assert result == "fake-gateway-object"

    asyncio.run(_check())


def test_get_spend_guard_resolves_via_lazy_resource() -> None:
    app = FastAPI()
    app.state.spend_guard = LazyResource(value="fake-spend-guard-object")

    async def _check() -> None:
        request = StarletteRequest({"type": "http", "app": app})
        result = await get_spend_guard(request)
        assert result == "fake-spend-guard-object"

    asyncio.run(_check())
