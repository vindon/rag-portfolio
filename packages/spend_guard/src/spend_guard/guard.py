from __future__ import annotations

import logging
import os
from enum import StrEnum

import asyncpg

from spend_guard import budget, circuit_breaker

logger = logging.getLogger(__name__)


class SpendDecision(StrEnum):
    ALLOW = "allow"
    DOWNGRADE_TO_LOCAL = "downgrade_to_local"
    BLOCK_GLOBAL_BREAKER = "block_global_breaker"
    BLOCK_VELOCITY_SPIKE = "block_velocity_spike"
    BLOCK_BUDGET_EXCEEDED = "block_budget_exceeded"

    @property
    def is_blocked(self) -> bool:
        return self in {
            SpendDecision.BLOCK_GLOBAL_BREAKER,
            SpendDecision.BLOCK_VELOCITY_SPIKE,
            SpendDecision.BLOCK_BUDGET_EXCEEDED,
        }


class SpendGuard:
    """Enforces spend caps and circuit breakers backed by Postgres.

    Every method here propagates asyncpg exceptions unchanged on database
    failure (connection refused, timeout, etc.) -- this package makes no
    fail-open/fail-closed decision on the caller's behalf. A caller wiring
    this into a request path must decide, and implement, its own policy for
    what happens when the database is unreachable.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        daily_cap_usd: float,
        monthly_cap_usd: float,
        circuit_breaker_threshold: int,
        circuit_breaker_cooldown_seconds: int,
        velocity_threshold_usd_per_minute: float,
    ) -> None:
        self._pool = pool
        self._daily_cap_usd = daily_cap_usd
        self._monthly_cap_usd = monthly_cap_usd
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._circuit_breaker_cooldown_seconds = circuit_breaker_cooldown_seconds
        self._velocity_threshold_usd_per_minute = velocity_threshold_usd_per_minute

    async def precheck(
        self, estimated_cost_usd: float, *, has_local_fallback: bool = True
    ) -> SpendDecision:
        async with self._pool.acquire() as conn:
            if await circuit_breaker.is_global_breaker_tripped(
                conn, cooldown_seconds=self._circuit_breaker_cooldown_seconds
            ):
                logger.warning("spend_guard.precheck.blocked reason=circuit_breaker_tripped")
                return SpendDecision.BLOCK_GLOBAL_BREAKER

            velocity = await circuit_breaker.get_spend_velocity(conn)
            if velocity >= self._velocity_threshold_usd_per_minute:
                await circuit_breaker.trip_global_breaker(conn)
                logger.critical(
                    "spend_guard.precheck.blocked reason=velocity_spike "
                    "velocity_usd_per_minute=%.4f threshold_usd_per_minute=%.4f",
                    velocity,
                    self._velocity_threshold_usd_per_minute,
                )
                return SpendDecision.BLOCK_VELOCITY_SPIKE

            status = await budget.get_budget_status(
                conn, daily_cap_usd=self._daily_cap_usd, monthly_cap_usd=self._monthly_cap_usd
            )
            projected_today = status.spent_today_usd + estimated_cost_usd
            projected_month = status.spent_this_month_usd + estimated_cost_usd
            over_budget = (
                projected_today > status.daily_cap_usd or projected_month > status.monthly_cap_usd
            )
            if over_budget and has_local_fallback:
                logger.warning(
                    "spend_guard.precheck.downgraded reason=budget_exceeded "
                    "projected_today_usd=%.4f daily_cap_usd=%.4f",
                    projected_today,
                    status.daily_cap_usd,
                )
                return SpendDecision.DOWNGRADE_TO_LOCAL
            if over_budget:
                logger.warning(
                    "spend_guard.precheck.blocked reason=budget_exceeded_no_fallback "
                    "projected_today_usd=%.4f daily_cap_usd=%.4f",
                    projected_today,
                    status.daily_cap_usd,
                )
                return SpendDecision.BLOCK_BUDGET_EXCEEDED

        return SpendDecision.ALLOW

    async def record_success(self, cost_usd: float, *, domain: str, provider: str) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await budget.record_spend(conn, domain=domain, provider=provider, cost_usd=cost_usd)
            await circuit_breaker.record_provider_success(conn, provider=provider)

    async def record_failure(self, *, provider: str) -> bool:
        async with self._pool.acquire() as conn:
            status = await circuit_breaker.record_provider_failure(
                conn, provider=provider, threshold=self._circuit_breaker_threshold
            )
        if status.tripped:
            logger.warning(
                "spend_guard.circuit_breaker.tripped provider=%s consecutive_failures=%d",
                provider,
                status.consecutive_failures,
            )
        return status.tripped

    async def is_provider_available(self, *, provider: str) -> bool:
        async with self._pool.acquire() as conn:
            return not await circuit_breaker.is_provider_tripped(
                conn, provider=provider, cooldown_seconds=self._circuit_breaker_cooldown_seconds
            )

    async def aclose(self) -> None:
        await self._pool.close()


async def create_spend_guard(
    dsn: str | None = None, *, env: dict[str, str] | None = None
) -> SpendGuard:
    source = env if env is not None else dict(os.environ)
    resolved_dsn = dsn if dsn is not None else source.get("DATABASE_URL", "")
    if not resolved_dsn:
        raise ValueError("DATABASE_URL is not configured")
    pool = await asyncpg.create_pool(
        resolved_dsn,
        min_size=int(source.get("SPEND_GUARD_POOL_MIN_SIZE", "1")),
        max_size=int(source.get("SPEND_GUARD_POOL_MAX_SIZE", "10")),
        command_timeout=float(source.get("SPEND_GUARD_COMMAND_TIMEOUT_SECONDS", "5.0")),
    )
    return SpendGuard(
        pool,
        daily_cap_usd=float(source.get("SPEND_GUARD_DAILY_CAP_USD", "1.0")),
        monthly_cap_usd=float(source.get("SPEND_GUARD_MONTHLY_CAP_USD", "20.0")),
        circuit_breaker_threshold=int(source.get("SPEND_GUARD_CIRCUIT_BREAKER_THRESHOLD", "5")),
        circuit_breaker_cooldown_seconds=int(
            source.get("SPEND_GUARD_CIRCUIT_BREAKER_COOLDOWN_SECONDS", "300")
        ),
        velocity_threshold_usd_per_minute=float(
            source.get("SPEND_GUARD_VELOCITY_THRESHOLD_USD_PER_MINUTE", "2.00")
        ),
    )
