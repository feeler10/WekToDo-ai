from enum import Enum
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


class ToolExecutionStatus(str, Enum):
    STARTED = 'STARTED'
    SUCCEEDED = 'SUCCEEDED'
    FAILED = 'FAILED'


class ToolExecutionLog(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str = Field(min_length=1)
    tenant_id: str = Field(default='default', min_length=1, max_length=200)
    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    action_id: str | None = None
    tool_name: str = Field(min_length=1)
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None = None
    confirmed: bool
    idempotency_key: str | None = None
    status: ToolExecutionStatus = ToolExecutionStatus.STARTED
    success: bool | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    error_message: str | None = None
    started_at: AwareDatetime = Field(default_factory=utc_now)
    completed_at: AwareDatetime | None = None

    @model_validator(mode='after')
    def validate_status(self) -> 'ToolExecutionLog':
        if self.status == ToolExecutionStatus.STARTED:
            if self.success is not None or self.completed_at is not None:
                raise ValueError('started tool execution cannot be completed')
        elif self.success is None or self.completed_at is None:
            raise ValueError('completed tool execution requires outcome and time')
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError('completed_at must not be earlier than started_at')
        return self
