from fastapi import FastAPI

from app.config import Settings


def create_app() -> FastAPI:
    app = FastAPI()
    settings = Settings()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    return app


app = create_app()
