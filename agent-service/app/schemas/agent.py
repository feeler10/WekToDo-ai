from enum import Enum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.audit import PendingAction
from app.schemas.draft import TaskDraft
from app.schemas.task import Task, TaskPriority
from app.schemas.subtask import SubtaskPlan, SubtaskPlanEdit


class ConfirmationAction(str, Enum):
    APPROVE = 'approve'
    EDIT = 'edit'
    REJECT = 'reject'
    REGENERATE = 'regenerate'


class TaskDraftEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None
    deadline: AwareDatetime | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)
    user_priority: TaskPriority | None = None

    @model_validator(mode='after')
    def require_change(self) -> 'TaskDraftEdit':
        if not self.model_fields_set:
            raise ValueError('At least one edited field must be provided')
        return self


class ConfirmationDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')

    action_id: str = Field(min_length=1)
    action: ConfirmationAction
    edits: TaskDraftEdit | SubtaskPlanEdit | None = None
    feedback: str | None = Field(default=None, max_length=1000)

    @model_validator(mode='after')
    def validate_action_payload(self) -> 'ConfirmationDecision':
        if self.action == ConfirmationAction.EDIT and self.edits is None:
            raise ValueError('edits are required for edit action')
        if self.action != ConfirmationAction.EDIT and self.edits is not None:
            raise ValueError('edits are only allowed for edit action')
        return self


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    timezone: str = Field(default='UTC', min_length=1)
    request_id: str = Field(min_length=1)


class AgentConfirmRequest(ConfirmationDecision):
    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    status: str
    thread_id: str
    message: str
    pending_action: PendingAction | None = None
    task_draft: TaskDraft | None = None
    task: Task | None = None
    tasks: list[Task] = Field(default_factory=list)
    candidates: list[Task] = Field(default_factory=list)
    subtask_plan: SubtaskPlan | None = None
    subtasks: list[Task] = Field(default_factory=list)
    parent_task: Task | None = None
    deleted_task_id: str | None = None
    deleted_task_ids: list[str] = Field(default_factory=list)
    deletion_tasks: list[Task] = Field(default_factory=list)
    parent_tasks: list[Task] = Field(default_factory=list)
