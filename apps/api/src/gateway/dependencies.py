from __future__ import annotations

from fastapi import Request
from model_gateway.gateway import ModelGateway
from spend_guard.guard import SpendGuard, create_spend_guard

from gateway.lazy import resolve_lazy


async def get_model_gateway(request: Request) -> ModelGateway:
    gateway: ModelGateway = request.app.state.gateway
    return gateway


async def get_spend_guard(request: Request) -> SpendGuard:
    return await resolve_lazy(
        request.app.state.spend_guard,
        create_spend_guard,
        error_detail="Spend Guard is temporarily unavailable.",
    )
