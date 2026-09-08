from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncpg


@dataclass(frozen=True)
class BreakerStatus:
    tripped: bool
    consecutive_failures: int


async def record_provider_failure(
    conn: asyncpg.pool.PoolConnectionProxy, *, provider: str, threshold: int
) -> BreakerStatus:
    row = await conn.fetchrow(
        """
        INSERT INTO circuit_breaker_state (provider, consecutive_failures, updated_at)
        VALUES ($1, 1, now())
        ON CONFLICT (provider) DO UPDATE
        SET consecutive_failures = circuit_breaker_state.consecutive_failures + 1,
            updated_at = now()
        RETURNING consecutive_failures
        """,
        provider,
    )
    assert row is not None
    failures = int(row["consecutive_failures"])
    tripped = failures >= threshold
    if tripped:
        # Unconditionally refresh tripped_at on every trip-condition hit — not
        # just the first time. A prior version of this only set tripped_at
        # WHERE tripped_at IS NULL, so once a provider's cooldown expired and
        # its trip flag was "stale" (still set from the earlier trip, just
        # outside the cooldown window), a fresh 5th-consecutive-failure would
        # correctly compute tripped=True here but the UPDATE would silently
        # no-op (tripped_at was already non-NULL), leaving the stale timestamp
        # in place — which is now further in the past, not closer, so
        # is_provider_tripped() would report the provider healthy forever
        # after the first cooldown, no matter how many more failures piled up.
        await conn.execute(
            "UPDATE circuit_breaker_state SET tripped_at = now() WHERE provider = $1",
            provider,
        )
    return BreakerStatus(tripped=tripped, consecutive_failures=failures)


async def record_provider_success(conn: asyncpg.pool.PoolConnectionProxy, *, provider: str) -> None:
    await conn.execute(
        """
        INSERT INTO circuit_breaker_state (provider, consecutive_failures, tripped_at, updated_at)
        VALUES ($1, 0, NULL, now())
        ON CONFLICT (provider) DO UPDATE
        SET consecutive_failures = 0, tripped_at = NULL, updated_at = now()
        """,
        provider,
    )


async def is_provider_tripped(
    conn: asyncpg.pool.PoolConnectionProxy, *, provider: str, cooldown_seconds: int
) -> bool:
    row = await conn.fetchrow(
        "SELECT tripped_at FROM circuit_breaker_state WHERE provider = $1", provider
    )
    if row is None or row["tripped_at"] is None:
        return False
    tripped_at: datetime = row["tripped_at"]
    return datetime.now(UTC) - tripped_at < timedelta(seconds=cooldown_seconds)


async def get_spend_velocity(conn: asyncpg.pool.PoolConnectionProxy) -> float:
    spent_last_minute = await conn.fetchval(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM budget_ledger "
        "WHERE created_at >= now() - interval '1 minute'"
    )
    return float(spent_last_minute)


async def trip_global_breaker(conn: asyncpg.pool.PoolConnectionProxy) -> None:
    await conn.execute("""
        INSERT INTO global_breaker_state (id, tripped_at, updated_at)
        VALUES (1, now(), now())
        ON CONFLICT (id) DO UPDATE SET tripped_at = now(), updated_at = now()
        """)


async def is_global_breaker_tripped(
    conn: asyncpg.pool.PoolConnectionProxy, *, cooldown_seconds: int
) -> bool:
    row = await conn.fetchrow("SELECT tripped_at FROM global_breaker_state WHERE id = 1")
    if row is None or row["tripped_at"] is None:
        return False
    tripped_at: datetime = row["tripped_at"]
    return datetime.now(UTC) - tripped_at < timedelta(seconds=cooldown_seconds)
