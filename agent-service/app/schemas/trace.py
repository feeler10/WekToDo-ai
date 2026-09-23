from enum import Enum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.task import utc_now
from app.schemas.audit import ToolExecutionLog


class TraceStatus(str, Enum):
    RUNNING = 'RUNNING'
    INTERRUPTED = 'INTERRUPTED'
    SUCCEEDED = 'SUCCEEDED'
    FAILED = 'FAILED'


class TraceEventType(str, Enum):
    REQUEST_STARTED = 'REQUEST_STARTED'
    REQUEST_COMPLETED = 'REQUEST_COMPLETED'
    NODE_STARTED = 'NODE_STARTED'
    NODE_COMPLETED = 'NODE_COMPLETED'
    MODEL_STARTED = 'MODEL_STARTED'
    MODEL_COMPLETED = 'MODEL_COMPLETED'
    INTERRUPTED = 'INTERRUPTED'
    RESUMED = 'RESUMED'
    TOOL_STARTED = 'TOOL_STARTED'
    TOOL_COMPLETED = 'TOOL_COMPLETED'
    ERROR = 'ERROR'


class TraceRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    trace_id: str = Field(min_length=1, max_length=100)
    parent_trace_id: str | None = Field(default=None, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    thread_id: str = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=1, max_length=200)
    operation: str = Field(min_length=1, max_length=50)
    status: TraceStatus = TraceStatus.RUNNING
    started_at: AwareDatetime = Field(default_factory=utc_now)
    completed_at: AwareDatetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode='after')
    def validate_completion(self) -> 'TraceRecord':
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError('completed_at must not be earlier than started_at')
        return self


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')

    event_id: str = Field(min_length=1, max_length=100)
    trace_id: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    thread_id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=1)
    event_type: TraceEventType
    node_name: str | None = Field(default=None, max_length=200)
    started_at: AwareDatetime = Field(default_factory=utc_now)
    completed_at: AwareDatetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    success: bool | None = None
    error_code: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_completion(self) -> 'TraceEvent':
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError('completed_at must not be earlier than started_at')
        return self


class TraceDetailResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    trace: TraceRecord
    events: list[TraceEvent] = Field(default_factory=list)
    tool_executions: list[ToolExecutionLog] = Field(default_factory=list)
