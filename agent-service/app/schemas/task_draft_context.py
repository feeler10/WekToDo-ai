from pydantic import Field, field_validator

from app.schemas.draft import TaskDraftCandidate, TaskDraftFieldName
from app.schemas.pending_operation import PendingOperationContextBase


class PendingTaskDraftClarification(PendingOperationContextBase):
    partial_draft: TaskDraftCandidate
    missing_fields: list[TaskDraftFieldName] = Field(min_length=1)

    @field_validator('missing_fields')
    @classmethod
    def unique_missing_fields(
        cls,
        value: list[TaskDraftFieldName],
    ) -> list[TaskDraftFieldName]:
        return list(dict.fromkeys(value))
