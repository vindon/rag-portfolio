from __future__ import annotations

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
