from fastapi import APIRouter, Depends, HTTPException, status
from sqlite3 import Connection

from app.dependencies import get_db
from app.schemas.users import CredentialCreate, TermsAgreementRead, UserCreate, UserRead
from services.auth_service import (
    create_user,
    list_users,
    mark_terms_agreed,
    upsert_credential_placeholder,
)

router = APIRouter()


@router.get("", response_model=list[UserRead])
def get_users(db: Connection = Depends(get_db)) -> list[UserRead]:
    return [UserRead(**row) for row in list_users(db)]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def post_user(payload: UserCreate, db: Connection = Depends(get_db)) -> UserRead:
    try:
        return UserRead(**create_user(db, payload))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/{user_id}/credential", status_code=status.HTTP_202_ACCEPTED)
def put_credential(
    user_id: int,
    payload: CredentialCreate,
    db: Connection = Depends(get_db),
) -> dict:
    upsert_credential_placeholder(db, user_id, payload)
    return {
        "status": "accepted",
        "detail": "credential storage is a placeholder; encryption will be implemented later",
    }


@router.post("/{user_id}/terms/agree", response_model=TermsAgreementRead)
def agree_terms(user_id: int, db: Connection = Depends(get_db)) -> TermsAgreementRead:
    try:
        return TermsAgreementRead(**mark_terms_agreed(db, user_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
