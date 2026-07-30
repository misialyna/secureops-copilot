from fastapi import FastAPI

from app.config import Settings
from app.rag.retriever import RetrievedChunk, get_retriever


def create_app() -> FastAPI:
    app = FastAPI()
    settings = Settings()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    @app.get("/search")
    async def search(q: str, top_k: int = 5) -> list[RetrievedChunk]:
        return get_retriever().search(q, top_k=top_k)

    return app


app = create_app()
