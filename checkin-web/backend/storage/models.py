SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    student_no TEXT,
    password_hash TEXT NOT NULL DEFAULT '',
    has_agreed_terms INTEGER NOT NULL DEFAULT 0,
    agreed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    school_username TEXT NOT NULL,
    encrypted_school_password TEXT NOT NULL,
    key_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auto_checkin_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    schedule_time TEXT NOT NULL DEFAULT '21:00',
    next_run_at TEXT,
    last_run_at TEXT,
    last_status TEXT,
    last_detail TEXT,
    last_audit_log_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- TODO: add checkin_tasks, checkin_runs, and api_events after the worker flow stabilizes.
"""
