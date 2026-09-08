import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from sqlite3 import Connection

from core.config import get_settings
from storage.database import connect

AUTO_CHECKIN_HOUR = 21
AUTO_CHECKIN_MINUTE = 0

_RUN_LOCK = threading.Lock()
_AUTO_THREAD_LOCK = threading.Lock()
_AUTO_THREAD: threading.Thread | None = None


def _legacy_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _tail_output(output: str, limit: int = 40) -> list[str]:
    return [line for line in output.splitlines() if line.strip()][-limit:]


def _next_scheduled_time(now: datetime | None = None) -> datetime:
    current = now or datetime.now()
    scheduled = current.replace(
        hour=AUTO_CHECKIN_HOUR,
        minute=AUTO_CHECKIN_MINUTE,
        second=0,
        microsecond=0,
    )
    if scheduled <= current:
        scheduled += timedelta(days=1)
    return scheduled


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dt_text(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _credential_password(row) -> str:
    key_id = str(row["key_id"] or "")
    encrypted_value = str(row["encrypted_school_password"] or "")
    if key_id == "plain-temporary":
        return encrypted_value
    raise ValueError("用户凭据不是可直接执行的临时明文凭据")


def _schedule_row_to_dict(row) -> dict:
    last_result = None
    if row["last_status"] or row["last_detail"]:
        last_result = {
            "status": row["last_status"] or "unknown",
            "detail": row["last_detail"] or "",
            "audit_log_path": row["last_audit_log_path"],
            "log_tail": [],
        }
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "school_username": row["school_username"],
        "enabled": bool(row["enabled"]),
        "schedule_time": row["schedule_time"],
        "next_run_at": row["next_run_at"],
        "last_run_at": row["last_run_at"],
        "last_result": last_result,
    }


def _list_auto_schedules(db: Connection) -> list[dict]:
    rows = db.execute(
        """
        SELECT
            s.user_id,
            u.username,
            u.display_name,
            c.school_username,
            s.enabled,
            s.schedule_time,
            s.next_run_at,
            s.last_run_at,
            s.last_status,
            s.last_detail,
            s.last_audit_log_path
        FROM auto_checkin_schedules s
        JOIN users u ON u.id = s.user_id
        JOIN credentials c ON c.user_id = s.user_id
        ORDER BY u.id
        """
    ).fetchall()
    return [_schedule_row_to_dict(row) for row in rows]


def _auto_status(db: Connection, detail: str | None = None) -> dict:
    schedules = _list_auto_schedules(db)
    enabled_schedules = [item for item in schedules if item["enabled"]]
    next_values = [item["next_run_at"] for item in enabled_schedules if item["next_run_at"]]
    last_values = [item["last_run_at"] for item in schedules if item["last_run_at"]]
    enabled = bool(enabled_schedules)
    if detail is None:
        detail = (
            f"已开启 {len(enabled_schedules)} 个用户的每日 21:00 自动打卡"
            if enabled
            else "自动打卡未开启"
        )
    return {
        "enabled": enabled,
        "status": "enabled" if enabled else "disabled",
        "detail": detail,
        "schedule_time": "21:00",
        "next_run_at": min(next_values) if next_values else None,
        "last_run_at": max(last_values) if last_values else None,
        "last_result": None,
        "schedules": schedules,
    }


def get_auto_checkin_status(db: Connection) -> dict:
    return _auto_status(db)


def _upsert_schedule(db: Connection, user_id: int) -> None:
    now = _now_text()
    next_run_at = _dt_text(_next_scheduled_time())
    db.execute(
        """
        INSERT INTO auto_checkin_schedules (
            user_id, enabled, schedule_time, next_run_at, created_at, updated_at
        )
        VALUES (?, 1, '21:00', ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            enabled = 1,
            schedule_time = '21:00',
            next_run_at = excluded.next_run_at,
            updated_at = excluded.updated_at
        """,
        (user_id, next_run_at, now, now),
    )
    db.commit()


def enable_auto_checkin(
    db: Connection,
    school_username: str,
    school_password: str,
) -> dict:
    start_auto_checkin_scheduler()
    now = _now_text()
    user = db.execute(
        "SELECT id FROM users WHERE username = ?",
        (school_username,),
    ).fetchone()
    if user:
        user_id = int(user["id"])
    else:
        cursor = db.execute(
            """
            INSERT INTO users (
                username, display_name, student_no, password_hash,
                has_agreed_terms, agreed_at, created_at
            )
            VALUES (?, NULL, NULL, '', 0, NULL, ?)
            """,
            (school_username, now),
        )
        user_id = int(cursor.lastrowid)
    db.execute(
        """
        INSERT INTO credentials (
            user_id, school_username, encrypted_school_password, key_id, updated_at
        )
        VALUES (?, ?, ?, 'plain-temporary', ?)
        ON CONFLICT(user_id) DO UPDATE SET
            school_username = excluded.school_username,
            encrypted_school_password = excluded.encrypted_school_password,
            key_id = excluded.key_id,
            updated_at = excluded.updated_at
        """,
        (user_id, school_username, school_password, now),
    )
    _upsert_schedule(db, user_id)
    return _auto_status(db, "已开启每日 21:00 自动打卡")


def enable_auto_checkin_for_username(db: Connection, username: str) -> dict:
    start_auto_checkin_scheduler()
    row = db.execute(
        """
        SELECT u.id, c.key_id, c.encrypted_school_password
        FROM users u
        JOIN credentials c ON c.user_id = u.id
        WHERE u.username = ?
        """,
        (username,),
    ).fetchone()
    if not row:
        raise ValueError("用户不存在或未保存凭据")
    _credential_password(row)
    _upsert_schedule(db, int(row["id"]))
    return _auto_status(db, f"已为 {username} 开启每日 21:00 自动打卡")


def start_auto_checkin_scheduler() -> None:
    global _AUTO_THREAD
    with _AUTO_THREAD_LOCK:
        if _AUTO_THREAD and _AUTO_THREAD.is_alive():
            return
        _AUTO_THREAD = threading.Thread(
            target=_auto_checkin_loop,
            name="auto-checkin-scheduler",
            daemon=True,
        )
        _AUTO_THREAD.start()


def _auto_checkin_loop() -> None:
    while True:
        time.sleep(15)
        now = datetime.now()
        settings = get_settings()
        with connect(settings.database_path) as db:
            rows = db.execute(
                """
                SELECT
                    s.user_id,
                    c.school_username,
                    c.encrypted_school_password,
                    c.key_id
                FROM auto_checkin_schedules s
                JOIN credentials c ON c.user_id = s.user_id
                WHERE s.enabled = 1
                  AND s.next_run_at IS NOT NULL
                  AND s.next_run_at <= ?
                ORDER BY s.next_run_at, s.user_id
                """,
                (_dt_text(now),),
            ).fetchall()

            for row in rows:
                try:
                    school_password = _credential_password(row)
                    result = run_checkin_now(row["school_username"], school_password)
                except Exception as exc:
                    result = {
                        "status": "failed",
                        "detail": str(exc),
                        "audit_log_path": None,
                        "log_tail": [],
                    }
                db.execute(
                    """
                    UPDATE auto_checkin_schedules
                    SET next_run_at = ?,
                        last_run_at = ?,
                        last_status = ?,
                        last_detail = ?,
                        last_audit_log_path = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        _dt_text(_next_scheduled_time(datetime.now())),
                        _dt_text(datetime.now()),
                        result.get("status"),
                        result.get("detail"),
                        result.get("audit_log_path"),
                        _now_text(),
                        row["user_id"],
                    ),
                )
                db.commit()


def run_checkin_now(school_username: str, school_password: str) -> dict:
    if not _RUN_LOCK.acquire(blocking=False):
        return {
            "status": "busy",
            "detail": "已有打卡流程正在执行，请稍后再试",
            "audit_log_path": None,
            "log_tail": [],
        }

    root = _legacy_root()
    audit_log_path = root / "audit_logs" / f"web_checkin_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "SWU_USERNAME": school_username,
        "SWU_PASSWORD": school_password,
    }
    command = [
        sys.executable,
        "login_and_checkin.py",
        "--cqtj-checkin",
        "--username",
        school_username,
        "--audit-log",
        str(audit_log_path),
    ]
    try:
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=240,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = "\n".join(part for part in (exc.stdout, exc.stderr) if part)
            return {
                "status": "timeout",
                "detail": "打卡流程超时，请查看浏览器登录窗口或审计日志后重试",
                "audit_log_path": str(audit_log_path),
                "log_tail": _tail_output(output),
            }

        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        log_tail = _tail_output(output)
        if completed.returncode == 0 and "[OK] 签到成功" in output:
            status = "success"
            detail = "签到成功"
        elif completed.returncode == 0 and "已签到" in output and "不重复提交" in output:
            status = "already-signed"
            detail = "今日任务已签到，未重复提交"
        elif completed.returncode == 0:
            status = "completed"
            detail = "流程已完成，请查看日志确认结果"
        else:
            status = "failed"
            detail = "签到失败，请查看日志输出"

        return {
            "status": status,
            "detail": detail,
            "audit_log_path": str(audit_log_path),
            "log_tail": log_tail,
        }
    finally:
        _RUN_LOCK.release()
