from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from model_gateway.gateway import ModelGateway
from model_gateway.types import ProviderError
from pydantic import BaseModel
from spend_guard.guard import SpendDecision, SpendGuard

from gateway.dependencies import get_model_gateway, get_spend_guard
from gateway.domains.hr_policy.prompts import build_prompt
from gateway.domains.hr_policy.retrieval import RetrievalIndex, build_hr_policy_index
from gateway.lazy import resolve_lazy

logger = logging.getLogger(__name__)


async def _safe_record(coro: Awaitable[object], *, what: str) -> None:
    """Best-effort spend_guard write: log critically on failure, never raise.

    spend_guard's own docstring is explicit that DB failures propagate
    unchanged and the caller owns the policy
    (packages/spend_guard/src/spend_guard/guard.py). For
    record_success/record_failure specifically, the underlying spend has
    already happened (or already failed) by the time we call this --
    refusing to return the answer/error the caller already paid for or
    received, just because the ledger write failed, would waste the spend a
    second time. Logging critically (not silently) is what makes a stuck
    ledger write observable in production instead of invisible.
    """
    try:
        await coro
    except Exception as exc:
        logger.critical("hr_policy.spend_guard_record_failed what=%s error=%s", what, exc)


router = APIRouter(prefix="/api/v1/hr_policy", tags=["hr_policy"])

_TOP_K = 4
_MAX_TOKENS = 512
_EXCERPT_MAX_CHARS = 200


class AskRequest(BaseModel):
    question: str


class Source(BaseModel):
    header: str
    excerpt: str
    relevance: float


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    provider_used: str


async def get_hr_policy_index(request: Request) -> RetrievalIndex:
    gateway: ModelGateway = request.app.state.gateway

    async def _build() -> RetrievalIndex:
        return await build_hr_policy_index(gateway)

    return await resolve_lazy(
        request.app.state.hr_policy_index,
        _build,
        error_detail="hr_policy is temporarily unavailable",
    )


def _last_attempted_provider(exc: ProviderError) -> str:
    return exc.attempted_providers[-1] if exc.attempted_providers else "unknown"


IndexDep = Annotated[RetrievalIndex, Depends(get_hr_policy_index)]
GatewayDep = Annotated[ModelGateway, Depends(get_model_gateway)]
SpendGuardDep = Annotated[SpendGuard, Depends(get_spend_guard)]


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    index: IndexDep,
    gateway: GatewayDep,
    spend_guard: SpendGuardDep,
) -> AskResponse:
    try:
        embed_outcome = await gateway.embed([body.question])
    except ProviderError as exc:
        await _safe_record(
            spend_guard.record_failure(provider=_last_attempted_provider(exc)),
            what="record_failure(embed)",
        )
        raise HTTPException(status_code=503, detail="hr_policy is temporarily unavailable") from exc

    await _safe_record(
        spend_guard.record_success(
            embed_outcome.estimated_cost_usd,
            domain="hr_policy",
            provider=embed_outcome.result.provider,
        ),
        what="record_success(embed)",
    )

    query_vector = embed_outcome.result.vectors[0]
    retrieved = index.search(query_vector, _TOP_K)
    messages = build_prompt(body.question, retrieved)

    estimate = gateway.estimate_precheck_cost(messages, max_tokens=_MAX_TOKENS)
    try:
        decision = await spend_guard.precheck(estimate, has_local_fallback=False)
    except Exception as exc:
        logger.critical("hr_policy.precheck_failed error=%s", exc)
        raise HTTPException(
            status_code=503, detail="Spend Guard is temporarily unavailable."
        ) from exc
    if decision == SpendDecision.BLOCK_BUDGET_EXCEEDED:
        raise HTTPException(
            status_code=503,
            detail="Daily budget for hr_policy has been reached. Try again tomorrow.",
        )
    if decision == SpendDecision.BLOCK_GLOBAL_BREAKER:
        raise HTTPException(
            status_code=503,
            detail="hr_policy is temporarily unavailable (circuit breaker open).",
        )
    if decision == SpendDecision.BLOCK_VELOCITY_SPIKE:
        raise HTTPException(
            status_code=503,
            detail="hr_policy is temporarily unavailable (unusual spend velocity detected).",
        )

    try:
        outcome = await gateway.complete(messages, max_tokens=_MAX_TOKENS)
    except ProviderError as exc:
        await _safe_record(
            spend_guard.record_failure(provider=_last_attempted_provider(exc)),
            what="record_failure(complete)",
        )
        raise HTTPException(
            status_code=503,
            detail="hr_policy is temporarily unavailable (all providers failed).",
        ) from exc

    await _safe_record(
        spend_guard.record_success(
            outcome.estimated_cost_usd, domain="hr_policy", provider=outcome.result.provider
        ),
        what="record_success(complete)",
    )

    sources = [
        Source(
            header=chunk.header,
            excerpt=chunk.text[:_EXCERPT_MAX_CHARS]
            + ("..." if len(chunk.text) > _EXCERPT_MAX_CHARS else ""),
            relevance=score,
        )
        for chunk, score in retrieved
    ]
    return AskResponse(
        answer=outcome.result.text, sources=sources, provider_used=outcome.result.provider
    )
