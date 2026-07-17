from collections.abc import Iterator
from sqlite3 import Connection

from core.config import get_settings
from storage.database import connect


def get_db() -> Iterator[Connection]:
    settings = get_settings()
    conn = connect(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()

