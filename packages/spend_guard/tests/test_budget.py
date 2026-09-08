from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest

from spend_guard.budget import get_budget_status, record_spend

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
async def test_get_budget_status_with_no_spend_is_zero(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    status = await get_budget_status(db_conn, daily_cap_usd=1.0, monthly_cap_usd=20.0)

    assert status.spent_today_usd == 0.0
    assert status.spent_this_month_usd == 0.0
    assert status.within_budget is True


@pytest.mark.anyio
async def test_record_spend_is_reflected_in_status(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    await record_spend(db_conn, domain="hr_policy", provider="groq", cost_usd=0.30)
    await record_spend(db_conn, domain="hr_policy", provider="groq", cost_usd=0.25)

    status = await get_budget_status(db_conn, daily_cap_usd=1.0, monthly_cap_usd=20.0)

    assert status.spent_today_usd == pytest.approx(0.55)
    assert status.spent_this_month_usd == pytest.approx(0.55)
    assert status.within_budget is True


@pytest.mark.anyio
async def test_within_budget_is_false_once_daily_cap_exceeded(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    await record_spend(db_conn, domain="hr_policy", provider="groq", cost_usd=1.50)

    status = await get_budget_status(db_conn, daily_cap_usd=1.0, monthly_cap_usd=20.0)

    assert status.within_budget is False
