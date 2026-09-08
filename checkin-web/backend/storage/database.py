import sqlite3
from pathlib import Path

from storage.models import SCHEMA_SQL


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA_SQL)
        _migrate_users_terms_columns(conn)
        conn.commit()


def _migrate_users_terms_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    if "has_agreed_terms" not in columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN has_agreed_terms INTEGER NOT NULL DEFAULT 0"
        )
    if "agreed_at" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN agreed_at TEXT")
