from fastapi import FastAPI

from gateway.domains.registry import DOMAIN_NAMES, make_domain_router


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Portfolio Gateway", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for name in DOMAIN_NAMES:
        app.include_router(make_domain_router(name))

    return app


app = create_app()
