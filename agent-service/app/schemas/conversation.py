from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.schemas.agent import AgentResponse


DEFAULT_TENANT_ID = 'default'


class ConversationScope(BaseModel):
    model_config = ConfigDict(extra='forbid')

    tenant_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=200)
    conversation_id: str = Field(min_length=1, max_length=200)


class ConversationRecord(ConversationScope):
    title: str = Field(min_length=1, max_length=100)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    message_count: int = Field(ge=0)


class ConversationMessage(ConversationScope):
    id: str = Field(min_length=1)
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=10000)
    operation_id: str = Field(min_length=1, max_length=300)
    created_at: AwareDatetime
    response: AgentResponse | None = None


class ConversationHistoryResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    tenant_id: str
    user_id: str
    conversation_id: str
    conversation: ConversationRecord | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)
