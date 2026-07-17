from fastapi import APIRouter

from services.log_service import list_logs_placeholder, cleanup_logs_placeholder

router = APIRouter()


@router.get("")
def list_logs() -> dict:
    return list_logs_placeholder()


@router.post("/cleanup")
def cleanup_logs() -> dict:
    return cleanup_logs_placeholder()

