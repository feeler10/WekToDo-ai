from enum import Enum

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.intent.models import TaskQueryIntent
from app.schemas.task import Task


class TaskDelete(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    expected_version: int = Field(ge=1)


class TaskDeleteResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    deleted_task_id: str = Field(min_length=1)
    parent_task: Task | None = None
    replayed: bool = False


class TaskDeleteMatchMode(str, Enum):
    EXACT = 'EXACT'
    CONTAINS = 'CONTAINS'


class TaskDeleteTargetScope(str, Enum):
    ALL_TASKS = 'ALL_TASKS'
    DIRECT_CHILDREN = 'DIRECT_CHILDREN'


class TaskDeleteParseResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    query: TaskQueryIntent = Field(default_factory=TaskQueryIntent)
    task_references: list[str] = Field(default_factory=list, max_length=50)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    match_mode: TaskDeleteMatchMode = TaskDeleteMatchMode.EXACT
    target_scope: TaskDeleteTargetScope = TaskDeleteTargetScope.ALL_TASKS
    parent_reference: str | None = Field(default=None, max_length=200)
    delete_all_matches: bool = False
    explicit_all_tasks: bool = False
    category: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=200)
    reason: str = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def validate_delete_parameters(self) -> 'TaskDeleteParseResult':
        self.task_references = _normalized_unique(self.task_references)
        self.keywords = _normalized_unique(self.keywords)
        if self.parent_reference is not None:
            self.parent_reference = self.parent_reference.strip() or None
        if self.needs_clarification:
            if not self.clarification_question:
                raise ValueError(
                    'clarification_question is required when clarification is needed'
                )
            return self
        if self.clarification_question is not None:
            raise ValueError(
                'clarification_question must be empty without clarification'
            )
        if self.target_scope == TaskDeleteTargetScope.DIRECT_CHILDREN:
            if not self.parent_reference:
                raise ValueError(
                    'DIRECT_CHILDREN requires parent_reference'
                )
        elif self.parent_reference is not None:
            raise ValueError(
                'parent_reference is only allowed for DIRECT_CHILDREN'
            )
        has_query_filter = bool(
            self.query.statuses
            or self.query.priorities
            or self.query.time_scope.value != 'UNSPECIFIED'
            or self.category
        )
        if not (
            self.task_references
            or self.keywords
            or has_query_filter
            or self.explicit_all_tasks
            or self.target_scope == TaskDeleteTargetScope.DIRECT_CHILDREN
        ):
            raise ValueError('At least one explicit deletion selector is required')
        if self.match_mode == TaskDeleteMatchMode.CONTAINS:
            if not self.keywords:
                raise ValueError('CONTAINS matching requires keywords')
            if not self.delete_all_matches:
                raise ValueError('CONTAINS matching must preview all matches')
        if len(self.task_references) > 1 and not self.delete_all_matches:
            raise ValueError('Multiple task references require delete_all_matches')
        return self


class TaskDeleteBatchItem(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    task_id: str = Field(min_length=1)
    expected_version: int = Field(ge=1)


class TaskDeleteBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    items: list[TaskDeleteBatchItem] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def require_unique_tasks(self) -> 'TaskDeleteBatch':
        ids = [item.task_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError('Batch task IDs must be unique')
        return self


class TaskDeleteBatchResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    deleted_task_ids: list[str]
    parent_tasks: list[Task] = Field(default_factory=list)
    replayed: bool = False


class PendingTaskDeleteSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    parse_result: TaskDeleteParseResult
    selection_kind: Literal['parent', 'task_reference']
    current_reference: str = Field(min_length=1, max_length=200)
    candidate_task_ids: list[str] = Field(min_length=2)
    candidate_versions: dict[str, int]
    resolved_parent_id: str | None = None
    resolved_references: dict[str, str] = Field(default_factory=dict)
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode='after')
    def validate_selection(self) -> 'PendingTaskDeleteSelection':
        if len(set(self.candidate_task_ids)) != len(self.candidate_task_ids):
            raise ValueError('candidate_task_ids must be unique')
        if set(self.candidate_versions) != set(self.candidate_task_ids):
            raise ValueError(
                'candidate_versions must cover exactly candidate_task_ids'
            )
        if self.expires_at <= self.created_at:
            raise ValueError('expires_at must be later than created_at')
        if self.selection_kind == 'task_reference' and (
            self.parse_result.target_scope
            == TaskDeleteTargetScope.DIRECT_CHILDREN
            and self.resolved_parent_id is None
        ):
            raise ValueError(
                'Scoped task selection requires resolved_parent_id'
            )
        if self.selection_kind == 'parent' and self.resolved_parent_id is not None:
            raise ValueError(
                'Parent selection cannot already have resolved_parent_id'
            )
        if not set(self.resolved_references).issubset(
            set(self.parse_result.task_references)
        ):
            raise ValueError(
                'resolved_references must belong to task_references'
            )
        return self


def _normalized_unique(values: list[str]) -> list[str]:
    normalized = [value.strip() for value in values if value.strip()]
    return list(dict.fromkeys(normalized))
