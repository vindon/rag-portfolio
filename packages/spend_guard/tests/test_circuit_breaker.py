from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest

from spend_guard.budget import record_spend
from spend_guard.circuit_breaker import (
    get_spend_velocity,
    is_global_breaker_tripped,
    is_provider_tripped,
    record_provider_failure,
    record_provider_success,
    trip_global_breaker,
)

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vinoth@localhost:5432/spend_guard_test"
)


@pytest.fixture
async def db_conn() -> AsyncIterator[asyncpg.pool.PoolConnectionProxy]:
    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=1)
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            yield conn
        finally:
            await tx.rollback()
    await pool.close()


@pytest.mark.anyio
async def test_provider_trips_after_threshold_consecutive_failures(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    for _ in range(4):
        status = await record_provider_failure(db_conn, provider="groq", threshold=5)
        assert status.tripped is False

    status = await record_provider_failure(db_conn, provider="groq", threshold=5)

    assert status.tripped is True
    assert status.consecutive_failures == 5
    assert await is_provider_tripped(db_conn, provider="groq", cooldown_seconds=300) is True


@pytest.mark.anyio
async def test_provider_success_resets_consecutive_failures(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    for _ in range(3):
        await record_provider_failure(db_conn, provider="groq", threshold=5)

    await record_provider_success(db_conn, provider="groq")

    status = await record_provider_failure(db_conn, provider="groq", threshold=5)
    assert status.consecutive_failures == 1


@pytest.mark.anyio
async def test_untripped_provider_is_not_tripped(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    assert await is_provider_tripped(db_conn, provider="never_seen", cooldown_seconds=300) is False


@pytest.mark.anyio
async def test_spend_velocity_reflects_recent_spend(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    assert await get_spend_velocity(db_conn) == 0.0

    await record_spend(db_conn, domain="hr_policy", provider="groq", cost_usd=0.75)

    assert await get_spend_velocity(db_conn) == pytest.approx(0.75)


@pytest.mark.anyio
async def test_global_breaker_trips_and_reports_tripped(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    assert await is_global_breaker_tripped(db_conn, cooldown_seconds=300) is False

    await trip_global_breaker(db_conn)

    assert await is_global_breaker_tripped(db_conn, cooldown_seconds=300) is True


@pytest.mark.anyio
async def test_provider_retrips_after_cooldown_expires_and_failures_resume(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    # Regression test for a real bug caught during plan review: a naive
    # "only set tripped_at if it's currently NULL" UPDATE means a provider
    # that trips once, has its cooldown expire, and then fails again would
    # never re-trip — is_provider_tripped() would report it as healthy
    # forever, no matter how many further consecutive failures accumulate,
    # because the stale tripped_at timestamp is already outside the cooldown
    # window and nothing ever refreshes it.
    for _ in range(5):
        await record_provider_failure(db_conn, provider="groq", threshold=5)
    assert await is_provider_tripped(db_conn, provider="groq", cooldown_seconds=300) is True

    # Simulate the cooldown window having already elapsed by back-dating
    # tripped_at, rather than sleeping 300 real seconds in a test.
    await db_conn.execute(
        "UPDATE circuit_breaker_state SET tripped_at = now() - interval '600 seconds' "
        "WHERE provider = $1",
        "groq",
    )
    assert await is_provider_tripped(db_conn, provider="groq", cooldown_seconds=300) is False

    status = await record_provider_failure(db_conn, provider="groq", threshold=5)

    assert status.tripped is True
    assert await is_provider_tripped(db_conn, provider="groq", cooldown_seconds=300) is True
