from pydantic import BaseModel, Field


class CheckinRunCreate(BaseModel):
    school_username: str = Field(min_length=1, max_length=120)
    school_password: str = Field(min_length=1)


class CheckinRunRead(BaseModel):
    status: str
    detail: str
    audit_log_path: str | None = None
    log_tail: list[str] = Field(default_factory=list)


class AutoCheckinScheduleCreate(BaseModel):
    school_username: str = Field(min_length=1, max_length=120)
    school_password: str = Field(min_length=1)


class AutoCheckinScheduleRead(BaseModel):
    user_id: int
    username: str
    display_name: str | None = None
    school_username: str
    enabled: bool
    schedule_time: str = "21:00"
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_result: CheckinRunRead | None = None


class AutoCheckinStatusRead(BaseModel):
    enabled: bool
    status: str
    detail: str
    schedule_time: str = "21:00"
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_result: CheckinRunRead | None = None
    schedules: list[AutoCheckinScheduleRead] = Field(default_factory=list)
