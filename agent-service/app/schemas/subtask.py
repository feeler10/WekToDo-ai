from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.task import Task


class SubtaskDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')

    step_key: str = Field(
        min_length=1,
        max_length=50,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$',
    )
    title: str = Field(min_length=1, max_length=200)
    description: str = ''
    order: int = Field(ge=1, le=100)
    estimated_minutes: int | None = Field(default=None, gt=0)
    deadline: AwareDatetime | None = None
    depends_on: list[str] = Field(default_factory=list)
    completion_weight: int = Field(default=1, ge=1, le=100)

    @field_validator('step_key', 'title')
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator('depends_on')
    @classmethod
    def unique_dependencies(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError('depends_on cannot contain empty step keys')
        if len(set(normalized)) != len(normalized):
            raise ValueError('depends_on must contain unique step keys')
        return normalized

    @model_validator(mode='after')
    def reject_self_dependency(self) -> 'SubtaskDraft':
        if self.step_key in self.depends_on:
            raise ValueError('A subtask cannot depend on itself')
        return self


class SubtaskPlanDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')

    summary: str | None = Field(default=None, max_length=1000)
    items: list[SubtaskDraft] = Field(min_length=1, max_length=10)


class SubtaskPlan(SubtaskPlanDraft):
    parent_task_id: str = Field(min_length=1)
    parent_version: int = Field(ge=1)
    warnings: list[str] = Field(default_factory=list)


class SubtaskPlanEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')

    summary: str | None = Field(default=None, max_length=1000)
    items: list[SubtaskDraft] = Field(min_length=1, max_length=10)


class SubtaskBatchCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    parent_task_id: str = Field(min_length=1)
    expected_parent_version: int = Field(ge=1)
    items: list[SubtaskDraft] = Field(min_length=1, max_length=10)


class SubtaskBatchResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    parent_task: Task
    subtasks: list[Task]
    replayed: bool = False


class TaskStatusUpdateResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    task: Task
    parent_task: Task | None = None
