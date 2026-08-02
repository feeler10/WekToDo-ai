from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.task import TaskStatus


class TaskQueryKind(str, Enum):
    LIST = 'list'
    TODAY = 'today'
    OVERDUE = 'overdue'
    DETAIL = 'detail'


class TaskReferenceUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    reference: str = Field(min_length=1)
    target_status: TaskStatus
