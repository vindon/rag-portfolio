from __future__ import annotations

from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class BudgetStatus:
    spent_today_usd: float
    spent_this_month_usd: float
    daily_cap_usd: float
    monthly_cap_usd: float

    @property
    def within_budget(self) -> bool:
        return (
            self.spent_today_usd < self.daily_cap_usd
            and self.spent_this_month_usd < self.monthly_cap_usd
        )


async def get_budget_status(
    conn: asyncpg.pool.PoolConnectionProxy, *, daily_cap_usd: float, monthly_cap_usd: float
) -> BudgetStatus:
    spent_today = await conn.fetchval(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM budget_ledger "
        "WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
    )
    spent_month = await conn.fetchval(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM budget_ledger "
        "WHERE created_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
    )
    return BudgetStatus(
        spent_today_usd=float(spent_today),
        spent_this_month_usd=float(spent_month),
        daily_cap_usd=daily_cap_usd,
        monthly_cap_usd=monthly_cap_usd,
    )


async def record_spend(
    conn: asyncpg.pool.PoolConnectionProxy, *, domain: str, provider: str, cost_usd: float
) -> None:
    await conn.execute(
        "INSERT INTO budget_ledger (domain, provider, cost_usd) VALUES ($1, $2, $3)",
        domain,
        provider,
        cost_usd,
    )
