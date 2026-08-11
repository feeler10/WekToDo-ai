from enum import Enum

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class TaskDraftFieldName(str, Enum):
    TITLE = 'title'
    DESCRIPTION = 'description'
    CATEGORY = 'category'
    DEADLINE = 'deadline'
    ESTIMATED_MINUTES = 'estimated_minutes'


class TaskDraftFields(BaseModel):
    model_config = ConfigDict(extra='forbid')

    description: str = ''
    category: str | None = None
    deadline: AwareDatetime | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)
    semantic_importance: int = Field(default=0, ge=0, le=100)
    impact_score: int = Field(default=0, ge=0, le=100)
    deadline_score: int = Field(default=0, ge=0, le=100)
    workload_risk_score: int = Field(default=0, ge=0, le=100)
    dependency_score: int = Field(default=0, ge=0, le=100)
    priority_reason: str | None = None


class TaskDraftCandidate(TaskDraftFields):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    missing_fields: list[TaskDraftFieldName] = Field(default_factory=list)
    clarification_question: str | None = Field(default=None, max_length=300)

    @field_validator('missing_fields')
    @classmethod
    def unique_missing_fields(
        cls,
        value: list[TaskDraftFieldName],
    ) -> list[TaskDraftFieldName]:
        return list(dict.fromkeys(value))


class TaskDraft(TaskDraftFields):
    title: str = Field(min_length=1, max_length=200)
