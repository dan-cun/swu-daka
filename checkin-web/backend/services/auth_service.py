from datetime import datetime, timezone
from sqlite3 import Connection, IntegrityError

from app.schemas.users import CredentialCreate, UserCreate


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_users(db: Connection) -> list[dict]:
    rows = db.execute(
        """
        SELECT
            id,
            username,
            display_name,
            student_no,
            has_agreed_terms,
            agreed_at,
            created_at
        FROM users
        ORDER BY id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def create_user(db: Connection, payload: UserCreate) -> dict:
    # password_hash is intentionally empty until password hashing is implemented.
    now = _utc_now()
    try:
        cursor = db.execute(
            """
            INSERT INTO users (
                username,
                display_name,
                student_no,
                password_hash,
                has_agreed_terms,
                agreed_at,
                created_at
            )
            VALUES (?, ?, ?, ?, 0, NULL, ?)
            """,
            (payload.username, payload.display_name, payload.student_no, "", now),
        )
        db.commit()
    except IntegrityError as exc:
        raise ValueError("username already exists") from exc
    row = db.execute(
        """
        SELECT
            id,
            username,
            display_name,
            student_no,
            has_agreed_terms,
            agreed_at,
            created_at
        FROM users
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


def upsert_credential_placeholder(
    db: Connection,
    user_id: int,
    payload: CredentialCreate,
) -> None:
    # Do not store plaintext school_password. This placeholder records metadata only.
    now = _utc_now()
    db.execute(
        """
        INSERT INTO credentials (
            user_id, school_username, encrypted_school_password, key_id, updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            school_username = excluded.school_username,
            encrypted_school_password = excluded.encrypted_school_password,
            key_id = excluded.key_id,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            payload.school_username,
            "__ENCRYPTION_NOT_IMPLEMENTED__",
            "placeholder",
            now,
        ),
    )
    db.commit()


def mark_terms_agreed(db: Connection, user_id: int) -> dict:
    agreed_at = _utc_now()
    cursor = db.execute(
        """
        UPDATE users
        SET has_agreed_terms = 1,
            agreed_at = ?
        WHERE id = ?
        """,
        (agreed_at, user_id),
    )
    if cursor.rowcount == 0:
        raise ValueError("user not found")
    db.commit()
    return {
        "user_id": user_id,
        "has_agreed_terms": True,
        "agreed_at": agreed_at,
    }
