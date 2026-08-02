from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.task import Task


class MatchKind(str, Enum):
    EXACT_ID = 'EXACT_ID'
    EXACT_TITLE = 'EXACT_TITLE'
    NORMALIZED_TITLE = 'NORMALIZED_TITLE'
    KEYWORD = 'KEYWORD'


class TaskMatchCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    task: Task
    match_kind: MatchKind


class TaskMatchResult(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    user_id: str = Field(min_length=1)
    reference: str
    candidates: list[TaskMatchCandidate] = Field(default_factory=list)

    @model_validator(mode='after')
    def require_user_isolation(self) -> 'TaskMatchResult':
        if any(
            candidate.task.user_id != self.user_id
            for candidate in self.candidates
        ):
            raise ValueError('All match candidates must belong to user_id')
        return self

    @property
    def unique_task(self) -> Task | None:
        if len(self.candidates) != 1:
            return None
        return self.candidates[0].task

    @property
    def tasks(self) -> list[Task]:
        return [candidate.task for candidate in self.candidates]

