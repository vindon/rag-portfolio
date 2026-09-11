from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from spend_guard.guard import SpendGuard, create_spend_guard
from spend_guard.schema import apply_schema

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres@localhost:5432/gateway_test"
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _admin_dsn_and_db_name() -> tuple[str, str]:
    parts = urlsplit(TEST_DATABASE_URL)
    db_name = parts.path.lstrip("/")
    admin_dsn = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))
    return admin_dsn, db_name


async def _ensure_database_exists() -> None:
    admin_dsn, db_name = _admin_dsn_and_db_name()
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


async def _apply_schema() -> None:
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await apply_schema(conn)
    finally:
        await conn.close()


def pytest_configure(config: pytest.Config) -> None:
    asyncio.run(_ensure_database_exists())
    asyncio.run(_apply_schema())


@pytest.fixture
async def clean_db() -> AsyncIterator[None]:
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await conn.execute("TRUNCATE budget_ledger, circuit_breaker_state, global_breaker_state")
        yield
    finally:
        await conn.execute("TRUNCATE budget_ledger, circuit_breaker_state, global_breaker_state")
        await conn.close()


@pytest.fixture
async def real_spend_guard(clean_db: None) -> AsyncIterator[SpendGuard]:
    guard = await create_spend_guard(
        TEST_DATABASE_URL,
        env={
            "SPEND_GUARD_DAILY_CAP_USD": "1.0",
            "SPEND_GUARD_MONTHLY_CAP_USD": "20.0",
            "SPEND_GUARD_CIRCUIT_BREAKER_THRESHOLD": "3",
            "SPEND_GUARD_CIRCUIT_BREAKER_COOLDOWN_SECONDS": "300",
            "SPEND_GUARD_VELOCITY_THRESHOLD_USD_PER_MINUTE": "100.0",
        },
    )
    try:
        yield guard
    finally:
        await guard.aclose()


@pytest.fixture
async def zero_budget_spend_guard(clean_db: None) -> AsyncIterator[SpendGuard]:
    """A SpendGuard whose daily cap is already exhausted by any positive spend.

    A dedicated fixture rather than mutating real_spend_guard's private fields
    in a test -- SpendGuard's public contract has no cap-mutation method, and
    reaching into `_daily_cap_usd` from test code would need a
    `# type: ignore[attr-defined]` to pass strict mypy, which this project
    treats as a real code-quality defect, not a convenience.
    """
    guard = await create_spend_guard(
        TEST_DATABASE_URL,
        env={
            "SPEND_GUARD_DAILY_CAP_USD": "0.0",
            "SPEND_GUARD_MONTHLY_CAP_USD": "0.0",
            "SPEND_GUARD_CIRCUIT_BREAKER_THRESHOLD": "3",
            "SPEND_GUARD_CIRCUIT_BREAKER_COOLDOWN_SECONDS": "300",
            "SPEND_GUARD_VELOCITY_THRESHOLD_USD_PER_MINUTE": "100.0",
        },
    )
    try:
        yield guard
    finally:
        await guard.aclose()
