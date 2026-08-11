from abc import ABC, abstractmethod

from app.schemas.agent import AgentResponse
from app.schemas.conversation import (
    ConversationHistoryResponse,
    ConversationScope,
)


class ConversationRepository(ABC):
    @abstractmethod
    async def append_exchange(
        self,
        *,
        scope: ConversationScope,
        operation_id: str,
        user_content: str,
        assistant_response: AgentResponse,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_history(
        self,
        *,
        scope: ConversationScope,
    ) -> ConversationHistoryResponse:
        raise NotImplementedError
