import pytest
from fastapi.testclient import TestClient

from gateway.domains.registry import DOMAIN_NAMES
from gateway.main import create_app


@pytest.mark.parametrize("domain", DOMAIN_NAMES)
def test_domain_status_endpoint(domain: str) -> None:
    client = TestClient(create_app())
    response = client.get(f"/api/v1/{domain}/status")
    assert response.status_code == 200
    assert response.json() == {"domain": domain, "status": "scaffolded"}


def test_domain_names_match_spec() -> None:
    assert DOMAIN_NAMES == [
        "hr_policy",
        "contract_review",
        "marketing_hub",
        "techdocs",
        "it_helpdesk",
    ]
