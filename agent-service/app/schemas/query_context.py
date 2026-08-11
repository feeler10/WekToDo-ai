from typing import Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.intent.enums import ClarificationReason, IntentType, TimeScope
from app.intent.models import IntentResult
from app.schemas.task import TaskPriority, TaskStatus


class TaskQueryIntentPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    time_scope: TimeScope | None = None
    statuses: set[TaskStatus] | None = None
    priorities: set[TaskPriority] | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    raw_time_expression: str | None = Field(default=None, max_length=100)
    task_reference: str | None = Field(default=None, max_length=200)

    @field_validator('raw_time_expression', 'task_reference')
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode='after')
    def require_patch_field(self) -> 'TaskQueryIntentPatch':
        if not self.model_fields_set:
            raise ValueError('At least one query patch field is required')
        return self


class PendingQueryClarification(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    original_intent: IntentResult
    clarification_reason: ClarificationReason
    missing_fields: list[str] = Field(min_length=1)
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator('missing_fields')
    @classmethod
    def unique_missing_fields(cls, value: list[str]) -> list[str]:
        if any(not field.strip() for field in value):
            raise ValueError('missing_fields cannot contain empty values')
        return list(dict.fromkeys(value))

    @model_validator(mode='after')
    def validate_pending_query(self) -> 'PendingQueryClarification':
        if self.original_intent.intent != IntentType.QUERY_TASKS:
            raise ValueError('original_intent must be QUERY_TASKS')
        if self.expires_at <= self.created_at:
            raise ValueError('expires_at must be later than created_at')
        return self


class PendingTaskSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    operation: IntentType
    candidate_task_ids: list[str] = Field(min_length=1)
    candidate_versions: dict[str, int]
    query_plan: dict[str, Any] | None = None
    include_subtasks: bool = False
    reference: str = Field(min_length=1, max_length=200)
    target_status: TaskStatus | None = None
    task_update_message: str | None = Field(default=None, max_length=2000)
    decomposition_message: str | None = Field(default=None, max_length=2000)
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator('candidate_task_ids')
    @classmethod
    def unique_candidate_ids(cls, value: list[str]) -> list[str]:
        if any(not task_id.strip() for task_id in value):
            raise ValueError('candidate_task_ids cannot contain empty values')
        if len(set(value)) != len(value):
            raise ValueError('candidate_task_ids must be unique')
        return value

    @model_validator(mode='after')
    def validate_pending_selection(self) -> 'PendingTaskSelection':
        allowed = {
            IntentType.QUERY_TASKS,
            IntentType.UPDATE_TASK,
            IntentType.UPDATE_TASK_STATUS,
            IntentType.DECOMPOSE_TASK,
            IntentType.DELETE_TASK,
        }
        if self.operation not in allowed:
            raise ValueError('operation must be a selectable task operation')
        if set(self.candidate_versions) != set(self.candidate_task_ids):
            raise ValueError(
                'candidate_versions must cover exactly candidate_task_ids'
            )
        if any(version < 1 for version in self.candidate_versions.values()):
            raise ValueError('candidate versions must be positive')
        if self.operation == IntentType.UPDATE_TASK_STATUS:
            if self.include_subtasks:
                raise ValueError('status update cannot request subtasks')
            if self.target_status is None:
                raise ValueError('target_status is required for status update')
            if self.query_plan is not None:
                raise ValueError('status update cannot carry query_plan')
            if self.task_update_message is not None:
                raise ValueError('status update cannot carry task_update_message')
            if self.decomposition_message is not None:
                raise ValueError('status update cannot carry decomposition_message')
        elif self.operation == IntentType.UPDATE_TASK:
            if self.include_subtasks:
                raise ValueError('task update cannot request subtasks')
            if not self.task_update_message:
                raise ValueError(
                    'task_update_message is required for task attribute update'
                )
            if self.query_plan is not None:
                raise ValueError('task update cannot carry query_plan')
            if self.decomposition_message is not None:
                raise ValueError('task update cannot carry decomposition_message')
        elif self.operation == IntentType.DECOMPOSE_TASK:
            if self.include_subtasks:
                raise ValueError('task decomposition cannot request subtasks')
            if not self.decomposition_message:
                raise ValueError(
                    'decomposition_message is required for task decomposition'
                )
            if self.query_plan is not None or self.target_status is not None:
                raise ValueError(
                    'task decomposition cannot carry query or status data'
                )
            if self.task_update_message is not None:
                raise ValueError(
                    'task decomposition cannot carry task_update_message'
                )
        elif self.operation == IntentType.DELETE_TASK:
            if self.include_subtasks:
                raise ValueError('task deletion cannot request subtasks')
            if (
                self.query_plan is not None
                or self.target_status is not None
                or self.task_update_message is not None
                or self.decomposition_message is not None
            ):
                raise ValueError('task deletion cannot carry unrelated data')
        else:
            if self.target_status is not None:
                raise ValueError('query selection cannot carry target_status')
            if self.task_update_message is not None:
                raise ValueError('query selection cannot carry task_update_message')
            if self.decomposition_message is not None:
                raise ValueError(
                    'query selection cannot carry decomposition_message'
                )
        if self.expires_at <= self.created_at:
            raise ValueError('expires_at must be later than created_at')
        return self


def missing_fields_for_reason(reason: ClarificationReason) -> list[str]:
    if reason == ClarificationReason.MISSING_TIME_SCOPE:
        return ['time_scope']
    if reason == ClarificationReason.MISSING_TASK_REFERENCE:
        return ['task_reference']
    if reason in {
        ClarificationReason.INVALID_TIME_RANGE,
        ClarificationReason.AMBIGUOUS_TIME_EXPRESSION,
    }:
        return ['time_range']
    return ['query']
