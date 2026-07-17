import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    env: str
    project_root: Path
    data_dir: Path
    database_path: Path
    log_dir: Path


def _resolve_path(value: str | None, base_dir: Path, default: Path) -> Path:
    if not value:
        return default
    path = Path(value)
    if not path.is_absolute():
        return base_dir / path
    return path


@lru_cache
def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = _resolve_path(os.getenv("CHECKIN_WEB_DATA_DIR"), project_root, project_root / "data")
    database_url = os.getenv("CHECKIN_WEB_DATABASE_URL", "sqlite:///./data/app.db")
    if database_url.startswith("sqlite:///"):
        raw_db_path = database_url.removeprefix("sqlite:///")
        database_path = _resolve_path(raw_db_path, project_root, project_root / "data" / "app.db")
    else:
        database_path = data_dir / "app.db"
    log_dir = _resolve_path(os.getenv("CHECKIN_WEB_LOG_DIR"), project_root, data_dir / "logs")
    return Settings(
        env=os.getenv("CHECKIN_WEB_ENV", "local"),
        project_root=project_root,
        data_dir=data_dir,
        database_path=database_path,
        log_dir=log_dir,
    )
