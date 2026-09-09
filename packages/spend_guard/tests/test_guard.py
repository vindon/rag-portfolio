from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest

from spend_guard.guard import SpendDecision, SpendGuard, create_spend_guard

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vinoth@localhost:5432/spend_guard_test"
)


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
async def guard(clean_db: None) -> AsyncIterator[SpendGuard]:
    # Velocity threshold is deliberately high (effectively disabled) for this shared
    # fixture, so budget-cap and circuit-breaker tests aren't accidentally tripped by
    # the velocity check (which runs *before* the budget check inside precheck()) when
    # they record a single spend close to the daily cap. test_precheck_blocks_when_
    # velocity_threshold_exceeded below builds its own guard with a low threshold
    # instead of using this fixture, to isolate that behavior.
    g = await create_spend_guard(
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
        yield g
    finally:
        await g.aclose()


@pytest.mark.anyio
async def test_precheck_allows_when_within_budget(guard: SpendGuard) -> None:
    decision = await guard.precheck(0.10)
    assert decision == SpendDecision.ALLOW


@pytest.mark.anyio
async def test_precheck_downgrades_when_over_daily_cap_and_local_fallback_available(
    guard: SpendGuard,
) -> None:
    await guard.record_success(0.95, domain="hr_policy", provider="groq")

    decision = await guard.precheck(0.10, has_local_fallback=True)

    assert decision == SpendDecision.DOWNGRADE_TO_LOCAL


@pytest.mark.anyio
async def test_precheck_blocks_when_over_daily_cap_and_no_local_fallback(
    guard: SpendGuard,
) -> None:
    await guard.record_success(0.95, domain="hr_policy", provider="groq")

    decision = await guard.precheck(0.10, has_local_fallback=False)

    assert decision == SpendDecision.BLOCK_BUDGET_EXCEEDED
    assert decision.is_blocked is True


@pytest.mark.anyio
async def test_precheck_blocks_when_velocity_threshold_exceeded_then_stays_blocked(
    clean_db: None,
) -> None:
    # Uses its own guard (not the shared `guard` fixture) so the low velocity
    # threshold here doesn't leak into the budget-cap tests above, and a high
    # daily cap so this test's spend can never be mistaken for a budget-cap trip.
    g = await create_spend_guard(
        TEST_DATABASE_URL,
        env={
            "SPEND_GUARD_DAILY_CAP_USD": "100.0",
            "SPEND_GUARD_MONTHLY_CAP_USD": "1000.0",
            "SPEND_GUARD_CIRCUIT_BREAKER_THRESHOLD": "3",
            "SPEND_GUARD_CIRCUIT_BREAKER_COOLDOWN_SECONDS": "300",
            "SPEND_GUARD_VELOCITY_THRESHOLD_USD_PER_MINUTE": "0.50",
        },
    )
    try:
        await g.record_success(0.60, domain="hr_policy", provider="groq")

        first_decision = await g.precheck(0.01)
        assert first_decision == SpendDecision.BLOCK_VELOCITY_SPIKE

        # A second precheck call finds the global breaker already tripped by
        # the first call — this is the BLOCK_GLOBAL_BREAKER path, distinct
        # from freshly detecting a velocity spike.
        second_decision = await g.precheck(0.01)
        assert second_decision == SpendDecision.BLOCK_GLOBAL_BREAKER
    finally:
        await g.aclose()


@pytest.mark.anyio
async def test_create_spend_guard_uses_production_defaults_and_does_not_trip_on_one_normal_call(
    clean_db: None,
) -> None:
    # Regression test for a real design gap caught during plan review: the
    # production-default daily cap ($1.00) and an earlier draft's default
    # velocity threshold ($0.50/min) were mutually incoherent — any single
    # realistic LLM call costing more than $0.50 would trip a platform-wide
    # halt on its very first use, which is not what the spec's "abnormal
    # spike (e.g. a runaway loop)" language describes. This test exercises
    # the actual production defaults (no env overrides at all beyond DSN)
    # and confirms one normal-sized call is fine, while a clearly-abnormal
    # single spend still trips it.
    g = await create_spend_guard(TEST_DATABASE_URL, env={})
    try:
        await g.record_success(0.30, domain="hr_policy", provider="groq")
        decision = await g.precheck(0.01)
        assert decision == SpendDecision.ALLOW

        await g.record_success(5.00, domain="hr_policy", provider="groq")
        decision = await g.precheck(0.01)
        assert decision.is_blocked is True
    finally:
        await g.aclose()


@pytest.mark.anyio
async def test_record_failure_trips_after_threshold_and_precheck_still_allows(
    guard: SpendGuard,
) -> None:
    tripped = False
    for _ in range(3):
        tripped = await guard.record_failure(provider="groq")

    assert tripped is True
    assert await guard.is_provider_available(provider="groq") is False
    # precheck() itself is budget/velocity-scoped, not per-provider — a tripped
    # provider is a signal the caller (Plan 2c's domain code) checks separately
    # via is_provider_available() before choosing which provider to force.
    assert await guard.precheck(0.05) == SpendDecision.ALLOW


@pytest.mark.anyio
async def test_record_success_resets_provider_availability(guard: SpendGuard) -> None:
    for _ in range(3):
        await guard.record_failure(provider="groq")
    assert await guard.is_provider_available(provider="groq") is False

    await guard.record_success(0.01, domain="hr_policy", provider="groq")

    assert await guard.is_provider_available(provider="groq") is True


@pytest.mark.anyio
async def test_breaker_state_persists_across_guard_restart(clean_db: None) -> None:
    # Exercises spec §5's headline reason for choosing Postgres over an
    # in-memory/SQLite store: "a process restart doesn't silently clear a
    # tripped breaker." Trip a provider via one SpendGuard instance, close
    # it (simulating a process restart), then build a brand-new SpendGuard
    # against the same DSN and confirm the trip is still visible.
    guard_a = await create_spend_guard(
        TEST_DATABASE_URL,
        env={"SPEND_GUARD_CIRCUIT_BREAKER_THRESHOLD": "2"},
    )
    for _ in range(2):
        await guard_a.record_failure(provider="groq")
    assert await guard_a.is_provider_available(provider="groq") is False
    await guard_a.aclose()

    guard_b = await create_spend_guard(TEST_DATABASE_URL, env={})
    try:
        assert await guard_b.is_provider_available(provider="groq") is False
    finally:
        await guard_b.aclose()


@pytest.mark.anyio
async def test_create_spend_guard_raises_without_dsn() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        await create_spend_guard(env={})
