from pydantic import Field

from app.schemas.pending_operation import PendingOperationContextBase
from app.schemas.task_attribute_update import TaskUpdateParseResult


class PendingTaskUpdateClarification(PendingOperationContextBase):
    task_id: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
    partial_result: TaskUpdateParseResult
