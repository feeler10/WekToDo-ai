from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.task import utc_now


class PendingAction(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    target_id: str | None = None
    payload: dict[str, Any]
    confirmation_status: Literal[
        'pending',
        'approved',
        'rejected',
        'cancelled',
    ] = 'pending'
    idempotency_key: str = Field(min_length=1)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    expires_at: AwareDatetime

    @model_validator(mode='after')
    def validate_expiry(self) -> 'PendingAction':
        if self.expires_at <= self.created_at:
            raise ValueError('expires_at must be later than created_at')
        return self


class ToolExecutionLog(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None = None
    confirmed: bool
    success: bool
    duration_ms: int = Field(ge=0)
    error_message: str | None = None
    created_at: AwareDatetime = Field(default_factory=utc_now)
