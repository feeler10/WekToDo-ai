from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.intent.enums import ClarificationReason, IntentType, TimeScope
from app.schemas.task import TaskPriority, TaskStatus, utc_now


class IntentRecognitionContext(BaseModel):
    message: str
    conversation_id: str | None = None
    user_id: str | None = None
    current_datetime: AwareDatetime = Field(default_factory=utc_now)
    business_timezone: str = Field(default='UTC', min_length=1)
    week_starts_on: Literal['Monday'] = 'Monday'
    recent_messages: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskQueryIntent(BaseModel):
    model_config = ConfigDict(extra='forbid')

    time_scope: TimeScope = TimeScope.UNSPECIFIED
    statuses: set[TaskStatus] | None = None
    priorities: set[TaskPriority] | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    raw_time_expression: str | None = Field(default=None, max_length=100)

    @field_validator('raw_time_expression')
    @classmethod
    def normalize_raw_time_expression(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode='after')
    def validate_time_range(self) -> 'TaskQueryIntent':
        if self.time_scope != TimeScope.CUSTOM and (
            self.start_at is not None or self.end_at is not None
        ):
            raise ValueError(
                'start_at and end_at are only allowed for CUSTOM'
            )
        if (
            self.start_at is not None
            and self.end_at is not None
            and self.end_at <= self.start_at
        ):
            raise ValueError('end_at must be later than start_at')
        return self


class IntentResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=200)
    task_reference: str | None = None
    target_status: TaskStatus | None = None
    query: TaskQueryIntent | None = None
    needs_clarification: bool = False
    clarification_reason: ClarificationReason | None = None
    clarification_question: str | None = Field(default=None, max_length=200)

    @field_validator('task_reference')
    @classmethod
    def normalize_task_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode='after')
    def validate_business_rules(self) -> 'IntentResult':
        if self.needs_clarification and not self.clarification_question:
            raise ValueError(
                'clarification_question is required when '
                'needs_clarification is true'
            )
        if not self.needs_clarification and self.clarification_question is not None:
            raise ValueError(
                'clarification_question must be empty when '
                'needs_clarification is false'
            )
        if (
            self.intent != IntentType.UPDATE_TASK_STATUS
            and self.target_status is not None
        ):
            raise ValueError(
                'target_status is only allowed for UPDATE_TASK_STATUS'
            )
        if (
            self.intent == IntentType.UPDATE_TASK_STATUS
            and not self.needs_clarification
            and self.target_status is None
        ):
            raise ValueError(
                'target_status is required for an unambiguous status update'
            )
        if self.intent != IntentType.QUERY_TASKS and self.query is not None:
            raise ValueError('query is only allowed for QUERY_TASKS')
        return self
