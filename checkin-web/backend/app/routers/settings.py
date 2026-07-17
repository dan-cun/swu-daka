from fastapi import APIRouter

from core.config import get_settings

router = APIRouter()


@router.get("")
def read_settings() -> dict:
    settings = get_settings()
    return {
        "env": settings.env,
        "data_dir": str(settings.data_dir),
        "database_path": str(settings.database_path),
        "log_dir": str(settings.log_dir),
    }

