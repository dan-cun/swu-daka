from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_db
from app.schemas.checkin import (
    AutoCheckinScheduleCreate,
    AutoCheckinStatusRead,
    CheckinRunCreate,
    CheckinRunRead,
)
from services.checkin_service import (
    enable_auto_checkin,
    enable_auto_checkin_for_username,
    get_auto_checkin_status,
    run_checkin_now,
)

router = APIRouter()


@router.post("/runs", response_model=CheckinRunRead)
def create_checkin_run(payload: CheckinRunCreate) -> CheckinRunRead:
    return CheckinRunRead(
        **run_checkin_now(payload.school_username, payload.school_password)
    )


@router.get("/auto", response_model=AutoCheckinStatusRead)
def read_auto_checkin_status(
    db: Connection = Depends(get_db),
) -> AutoCheckinStatusRead:
    return AutoCheckinStatusRead(**get_auto_checkin_status(db))


@router.post("/auto", response_model=AutoCheckinStatusRead)
def enable_auto_checkin_schedule(
    payload: AutoCheckinScheduleCreate,
    db: Connection = Depends(get_db),
) -> AutoCheckinStatusRead:
    return AutoCheckinStatusRead(
        **enable_auto_checkin(db, payload.school_username, payload.school_password)
    )


@router.post("/auto/users/{username}", response_model=AutoCheckinStatusRead)
def enable_auto_checkin_user(
    username: str,
    db: Connection = Depends(get_db),
) -> AutoCheckinStatusRead:
    try:
        return AutoCheckinStatusRead(**enable_auto_checkin_for_username(db, username))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs")
def list_checkin_runs() -> dict:
    return {"items": [], "detail": "checkin run persistence is not implemented yet"}
