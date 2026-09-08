from fastapi import APIRouter

DOMAIN_NAMES: list[str] = [
    "hr_policy",
    "contract_review",
    "marketing_hub",
    "techdocs",
    "it_helpdesk",
]


def make_domain_router(name: str) -> APIRouter:
    router = APIRouter(prefix=f"/api/v1/{name}", tags=[name])

    @router.get("/status")
    def status() -> dict[str, str]:
        return {"domain": name, "status": "scaffolded"}

    return router
