from __future__ import annotations

import os

import asyncpg
import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vinoth@localhost:5432/spend_guard_test"
)


@pytest.mark.anyio
async def test_schema_tables_exist_after_bootstrap() -> None:
    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=1)
    try:
        async with pool.acquire() as conn:
            tables = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY($1)",
                ["budget_ledger", "circuit_breaker_state", "global_breaker_state"],
            )
        names = {row["table_name"] for row in tables}
        assert names == {"budget_ledger", "circuit_breaker_state", "global_breaker_state"}
    finally:
        await pool.close()
