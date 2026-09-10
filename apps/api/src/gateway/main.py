from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from model_gateway.gateway import ModelGateway
from spend_guard.guard import SpendGuard, create_spend_guard

from gateway.domains.hr_policy.retrieval import RetrievalIndex, build_hr_policy_index
from gateway.domains.hr_policy.router import router as hr_policy_router
from gateway.domains.registry import DOMAIN_NAMES, make_domain_router
from gateway.lazy import LazyResource

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    gateway = ModelGateway()
    app.state.gateway = gateway

    spend_guard_resource: LazyResource[SpendGuard] = LazyResource()
    try:
        spend_guard_resource.value = await create_spend_guard()
    except Exception as exc:
        logger.critical("gateway.startup.spend_guard_init_failed error=%s", exc)
        spend_guard_resource.build_error = str(exc)
    app.state.spend_guard = spend_guard_resource

    hr_policy_index_resource: LazyResource[RetrievalIndex] = LazyResource()
    try:
        hr_policy_index_resource.value = await build_hr_policy_index(gateway)
    except Exception as exc:
        logger.critical("hr_policy.startup.index_build_failed error=%s", exc)
        hr_policy_index_resource.build_error = str(exc)
    app.state.hr_policy_index = hr_policy_index_resource

    yield

    if spend_guard_resource.value is not None:
        await spend_guard_resource.value.aclose()
    await gateway.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Portfolio Gateway", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for name in DOMAIN_NAMES:
        if name == "hr_policy":
            app.include_router(hr_policy_router)
        else:
            app.include_router(make_domain_router(name))

    return app


app = create_app()
