from fastapi import APIRouter

from services.checkin_service import start_checkin_placeholder

router = APIRouter()


@router.post("/runs")
def create_checkin_run(user_id: int) -> dict:
    return start_checkin_placeholder(user_id)


@router.get("/runs")
def list_checkin_runs() -> dict:
    return {"items": [], "detail": "checkin run persistence is not implemented yet"}

