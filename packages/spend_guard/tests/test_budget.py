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


@pytest.mark.anyio
async def test_monthly_cap_exceeded_when_daily_spend_is_low(
    db_conn: asyncpg.pool.PoolConnectionProxy,
) -> None:
    # On day 1 of the UTC month, "this month" and "today" are the same
    # window, so a fixture spend that's in-month but not-today is not
    # constructible -- skip honestly rather than assert something false.
    is_first_of_utc_month = await db_conn.fetchval(
        "SELECT extract(day from now() AT TIME ZONE 'UTC') = 1"
    )
    if is_first_of_utc_month:
        pytest.skip("month-start and day-start coincide on day 1 of the UTC month")

    # Insert a spend earlier this month (but not today) so month-to-date is
    # high while today's spend is low -- this must be caught independently
    # of the daily-cap path, which every other test in this file exercises.
    # record_spend always writes created_at = now(), so back-date directly
    # via SQL instead, the same technique the circuit-breaker re-trip
    # regression test uses. Anchored to the start of the current UTC month
    # (matching get_budget_status's UTC-pinned boundary) rather than a fixed
    # "N days ago" offset, so the test is correct no matter what day of the
    # month it runs on.
    await db_conn.execute(
        "INSERT INTO budget_ledger (domain, provider, cost_usd, created_at) "
        "VALUES ($1, $2, $3, "
        "date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' + interval '1 hour')",
        "test_domain",
        "test_provider",
        15.0,
    )
    status = await get_budget_status(db_conn, daily_cap_usd=1.0, monthly_cap_usd=20.0)
    assert status.spent_today_usd == pytest.approx(0.0)
    assert status.spent_this_month_usd == pytest.approx(15.0)
    assert status.within_budget is True  # 15 <= 20 monthly cap, 0 <= 1 daily cap

    # Now push monthly total over the cap.
    await db_conn.execute(
        "INSERT INTO budget_ledger (domain, provider, cost_usd, created_at) "
        "VALUES ($1, $2, $3, "
        "date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' + interval '2 hours')",
        "test_domain",
        "test_provider",
        10.0,
    )
    status = await get_budget_status(db_conn, daily_cap_usd=1.0, monthly_cap_usd=20.0)
    assert status.spent_this_month_usd == pytest.approx(25.0)
    assert status.within_budget is False  # 25 > 20 monthly cap, despite $0 spent today
