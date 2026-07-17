from fastapi import FastAPI

from app.routers import checkin, logs, settings, users
from core.config import get_settings
from storage.database import init_database


def create_app() -> FastAPI:
    app_settings = get_settings()
    app = FastAPI(title="Checkin Web", version="0.1.0")

    @app.on_event("startup")
    def on_startup() -> None:
        init_database(settings.database_path)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "env": app_settings.env}

    app.include_router(users.router, prefix="/api/users", tags=["users"])
    app.include_router(checkin.router, prefix="/api/checkin", tags=["checkin"])
    app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
    return app


app = create_app()
