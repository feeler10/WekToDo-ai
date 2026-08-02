from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.intent.enums import IntentType
from app.schemas.task import TaskStatus


class IntentRecognitionContext(BaseModel):
    message: str
    conversation_id: str | None = None
    user_id: str | None = None
    recent_messages: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class IntentResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=200)
    task_reference: str | None = None
    target_status: TaskStatus | None = None
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=200)

    @model_validator(mode='after')
    def validate_business_rules(self) -> 'IntentResult':
        if self.needs_clarification and not self.clarification_question:
            raise ValueError(
                'clarification_question is required when '
                'needs_clarification is true'
            )
        if not self.needs_clarification and self.clarification_question is not None:
            raise ValueError(
                'clarification_question must be empty when '
                'needs_clarification is false'
            )
        if (
            self.intent != IntentType.UPDATE_TASK_STATUS
            and self.target_status is not None
        ):
            raise ValueError(
                'target_status is only allowed for UPDATE_TASK_STATUS'
            )
        if (
            self.intent == IntentType.UPDATE_TASK_STATUS
            and not self.needs_clarification
            and self.target_status is None
        ):
            raise ValueError(
                'target_status is required for an unambiguous status update'
            )
        return self
