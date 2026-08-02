from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    TODO = 'TODO'
    DOING = 'DOING'
    DONE = 'DONE'
    BLOCKED = 'BLOCKED'
    CANCELLED = 'CANCELLED'


class TaskPriority(str, Enum):
    URGENT = 'URGENT'
    HIGH = 'HIGH'
    MEDIUM = 'MEDIUM'
    LOW = 'LOW'


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    parent_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str = ''
    category: str | None = None
    deadline: AwareDatetime | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)
    ai_priority: TaskPriority | None = None
    user_priority: TaskPriority | None = None
    urgency_score: int | None = Field(default=None, ge=0, le=100)
    priority_reason: str | None = None
    is_ai_generated: bool = False


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None
    deadline: AwareDatetime | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)
    actual_minutes: int | None = Field(default=None, ge=0)
    user_priority: TaskPriority | None = None

    @model_validator(mode='after')
    def require_change(self) -> 'TaskUpdate':
        update_fields = {
            'title',
            'description',
            'category',
            'deadline',
            'estimated_minutes',
            'actual_minutes',
            'user_priority',
        }
        if not self.model_fields_set.intersection(update_fields):
            raise ValueError('At least one task field must be provided')
        return self


class TaskStatusUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    current_status: TaskStatus
    target_status: TaskStatus
    expected_version: int = Field(ge=1)
    confirmed_reopen: bool = False


class TaskQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    statuses: set[TaskStatus] | None = None
    priorities: set[TaskPriority] | None = None
    category: str | None = None
    deadline_from: AwareDatetime | None = None
    deadline_to: AwareDatetime | None = None
    overdue_before: AwareDatetime | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode='after')
    def validate_deadline_range(self) -> 'TaskQuery':
        if (
            self.deadline_from is not None
            and self.deadline_to is not None
            and self.deadline_to <= self.deadline_from
        ):
            raise ValueError('deadline_to must be later than deadline_from')
        return self


class Task(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    parent_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str = ''
    category: str | None = None
    status: TaskStatus = TaskStatus.TODO
    deadline: AwareDatetime | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)
    actual_minutes: int | None = Field(default=None, ge=0)
    ai_priority: TaskPriority | None = None
    user_priority: TaskPriority | None = None
    effective_priority: TaskPriority | None = None
    priority_source: Literal['ai', 'user'] | None = None
    urgency_score: int | None = Field(default=None, ge=0, le=100)
    priority_reason: str | None = None
    progress: int = Field(default=0, ge=0, le=100)
    is_ai_generated: bool = False
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)
    completed_at: AwareDatetime | None = None
    version: int = Field(default=1, ge=1)

    @model_validator(mode='after')
    def validate_consistency(self) -> 'Task':
        if self.updated_at < self.created_at:
            raise ValueError('updated_at must not be earlier than created_at')
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError('completed_at must not be earlier than created_at')

        expected_priority = self.user_priority or self.ai_priority
        expected_source: Literal['ai', 'user'] | None = None
        if self.user_priority is not None:
            expected_source = 'user'
        elif self.ai_priority is not None:
            expected_source = 'ai'

        if (
            self.effective_priority is not None
            and self.effective_priority != expected_priority
        ):
            raise ValueError('effective_priority must follow user or AI priority')
        if self.priority_source is not None and self.priority_source != expected_source:
            raise ValueError('priority_source does not match effective priority')

        object.__setattr__(self, 'effective_priority', expected_priority)
        object.__setattr__(self, 'priority_source', expected_source)
        return self


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[Task]
    total: int = Field(ge=0)
