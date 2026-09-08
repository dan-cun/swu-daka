from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    display_name: str | None = Field(default=None, max_length=120)
    student_no: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, min_length=1)


class UserRead(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    student_no: str | None = None
    has_agreed_terms: bool = False
    agreed_at: datetime | None = None
    created_at: datetime


class CredentialCreate(BaseModel):
    school_username: str = Field(min_length=1, max_length=120)
    school_password: str = Field(min_length=1)


class TermsAgreementRead(BaseModel):
    user_id: int
    has_agreed_terms: bool
    agreed_at: datetime
