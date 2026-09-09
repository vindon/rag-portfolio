from __future__ import annotations

from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class BreakerStatus:
    tripped: bool
    consecutive_failures: int


async def record_provider_failure(
    conn: asyncpg.pool.PoolConnectionProxy, *, provider: str, threshold: int
) -> BreakerStatus:
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
    # The CASE below has no `AND tripped_at IS NULL` guard for exactly this
    # reason: it must refresh tripped_at every time the trip condition is
    # met, not only the first time.
    row = await conn.fetchrow(
        """
        INSERT INTO circuit_breaker_state (provider, consecutive_failures, updated_at)
        VALUES ($1, 1, now())
        ON CONFLICT (provider) DO UPDATE
        SET consecutive_failures = circuit_breaker_state.consecutive_failures + 1,
            tripped_at = CASE
                WHEN circuit_breaker_state.consecutive_failures + 1 >= $2 THEN now()
                ELSE circuit_breaker_state.tripped_at
            END,
            updated_at = now()
        RETURNING consecutive_failures, tripped_at IS NOT NULL AS tripped
        """,
        provider,
        threshold,
    )
    if row is None:
        raise RuntimeError(f"record_provider_failure: upsert returned no row for {provider!r}")
    return BreakerStatus(
        tripped=bool(row["tripped"]), consecutive_failures=int(row["consecutive_failures"])
    )


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
    return bool(
        await conn.fetchval(
            """
            SELECT tripped_at IS NOT NULL AND tripped_at > now() - make_interval(secs => $2)
            FROM circuit_breaker_state WHERE provider = $1
            """,
            provider,
            float(cooldown_seconds),
        )
        or False
    )


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
    return bool(
        await conn.fetchval(
            """
            SELECT tripped_at IS NOT NULL AND tripped_at > now() - make_interval(secs => $1)
            FROM global_breaker_state WHERE id = 1
            """,
            float(cooldown_seconds),
        )
        or False
    )
