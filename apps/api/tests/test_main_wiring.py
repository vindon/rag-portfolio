from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from model_gateway.gateway import ModelGateway
from model_gateway.settings import GatewaySettings

from gateway.dependencies import get_model_gateway, get_spend_guard
from gateway.domains.hr_policy.retrieval import Chunk, RetrievalIndex
from gateway.domains.hr_policy.router import get_hr_policy_index
from gateway.main import create_app


def _empty_gateway() -> ModelGateway:
    settings = GatewaySettings(
        llm_primary="",
        llm_secondary="",
        llm_local="",
        embed_primary="",
        embed_secondary="",
        timeout_seconds=5.0,
        max_retries=0,
        llm_providers={},
        embed_providers={},
    )
    return ModelGateway(settings)


def test_hr_policy_ask_route_is_mounted_not_the_scaffold() -> None:
    app = create_app()
    app.dependency_overrides[get_model_gateway] = _empty_gateway
    app.dependency_overrides[get_spend_guard] = lambda: None
    app.dependency_overrides[get_hr_policy_index] = lambda: RetrievalIndex(
        [Chunk(header="H", text="T", vector=[1.0])]
    )

    client = TestClient(app)
    response = client.get("/api/v1/hr_policy/status")

    # The scaffold's /status route no longer exists for hr_policy -- only /ask does.
    assert response.status_code == 404


def test_other_domains_still_scaffolded() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/contract_review/status")

    assert response.status_code == 200
    assert response.json() == {"domain": "contract_review", "status": "scaffolded"}


def test_health_still_ok_without_lifespan() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_survives_spend_guard_init_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _broken_create_spend_guard(*args: object, **kwargs: object) -> object:
        raise ConnectionError("simulated Postgres outage")

    async def _fake_build_hr_policy_index(*args: object, **kwargs: object) -> object:
        return object()  # never touched by /health; avoids any real network/embedding call

    monkeypatch.setattr("gateway.main.create_spend_guard", _broken_create_spend_guard)
    monkeypatch.setattr("gateway.main.build_hr_policy_index", _fake_build_hr_policy_index)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert app.state.spend_guard.value is None
    assert app.state.spend_guard.build_error is not None
    assert app.state.hr_policy_index.value is not None  # the other resource is unaffected


def test_health_survives_hr_policy_index_build_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSpendGuard:
        async def aclose(self) -> None:
            pass

    async def _fake_create_spend_guard(*args: object, **kwargs: object) -> object:
        return _FakeSpendGuard()

    async def _broken_build_hr_policy_index(*args: object, **kwargs: object) -> object:
        raise ValueError("simulated index build failure")

    monkeypatch.setattr("gateway.main.create_spend_guard", _fake_create_spend_guard)
    monkeypatch.setattr("gateway.main.build_hr_policy_index", _broken_build_hr_policy_index)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert app.state.hr_policy_index.value is None
    assert app.state.hr_policy_index.build_error is not None
    assert app.state.spend_guard.value is not None  # the other resource is unaffected
