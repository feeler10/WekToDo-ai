from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskFieldName(str, Enum):
    TITLE = 'title'
    DESCRIPTION = 'description'
    CATEGORY = 'category'
    DEADLINE = 'deadline'
    ESTIMATED_MINUTES = 'estimated_minutes'
    USER_PRIORITY = 'user_priority'


class TaskFieldOperation(str, Enum):
    SET = 'SET'
    CLEAR = 'CLEAR'


class TaskFieldChange(BaseModel):
    model_config = ConfigDict(extra='forbid')

    field: TaskFieldName
    operation: TaskFieldOperation
    value: Any = None
    raw_expression: str | None = Field(default=None, max_length=200)

    @model_validator(mode='after')
    def validate_operation_value(self) -> 'TaskFieldChange':
        if self.operation == TaskFieldOperation.CLEAR and self.value is not None:
            raise ValueError('CLEAR operation requires a null value')
        if self.operation == TaskFieldOperation.SET and self.value is None:
            raise ValueError('SET operation requires a value')
        if (
            self.field == TaskFieldName.TITLE
            and self.operation == TaskFieldOperation.CLEAR
        ):
            raise ValueError('title cannot be cleared')
        return self


class TaskUpdateParseResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    changes: list[TaskFieldChange] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=300)
    reason: str = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def validate_result(self) -> 'TaskUpdateParseResult':
        fields = [change.field for change in self.changes]
        if len(fields) != len(set(fields)):
            raise ValueError('Each task field can only be changed once')
        if self.needs_clarification and not self.clarification_question:
            raise ValueError(
                'clarification_question is required when clarification is needed'
            )
        if not self.needs_clarification and self.clarification_question is not None:
            raise ValueError(
                'clarification_question must be empty when clarification is not needed'
            )
        if not self.needs_clarification and not self.changes:
            raise ValueError('At least one change is required')
        return self
