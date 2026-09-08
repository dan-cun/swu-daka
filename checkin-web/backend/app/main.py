from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import checkin, settings, users
from core.config import get_settings
from services.checkin_service import start_auto_checkin_scheduler
from storage.database import init_database


def create_app() -> FastAPI:
    app_settings = get_settings()
    app = FastAPI(title="Checkin Web", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def on_startup() -> None:
        init_database(app_settings.database_path)
        start_auto_checkin_scheduler()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "env": app_settings.env}

    app.include_router(users.router, prefix="/api/users", tags=["users"])
    app.include_router(checkin.router, prefix="/api/checkin", tags=["checkin"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
    return app


app = create_app()
