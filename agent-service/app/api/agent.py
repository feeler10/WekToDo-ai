from typing import Annotated

from fastapi import APIRouter, Path, Query, Request

from app.core.exceptions import AppError
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest, AgentResponse
from app.schemas.conversation import ConversationHistoryResponse
from app.services.agent import (
    AgentThreadConflictError,
    AgentThreadNotFoundError,
    TaskAgentService,
)

router = APIRouter(prefix='/api/agent', tags=['agent'])


def _service(request: Request) -> TaskAgentService:
    service = getattr(request.app.state, 'agent_service', None)
    if service is None:
        raise AppError(
            'Agent service is not configured',
            code='agent_unavailable',
            status_code=503,
        )
    return service


@router.post('/chat', response_model=AgentResponse)
async def chat(payload: AgentChatRequest, request: Request) -> AgentResponse:
    try:
        return await _service(request).chat(payload)
    except AgentThreadConflictError as exc:
        raise AppError(str(exc), code='thread_conflict', status_code=409) from exc


@router.post('/confirm', response_model=AgentResponse)
async def confirm(payload: AgentConfirmRequest, request: Request) -> AgentResponse:
    try:
        return await _service(request).confirm(payload)
    except AgentThreadNotFoundError as exc:
        raise AppError(str(exc), code='thread_not_found', status_code=404) from exc
    except AgentThreadConflictError as exc:
        raise AppError(str(exc), code='thread_conflict', status_code=409) from exc


@router.get(
    '/conversations/{thread_id}',
    response_model=ConversationHistoryResponse,
)
async def get_conversation_history(
    thread_id: Annotated[str, Path(min_length=1, max_length=200)],
    user_id: Annotated[str, Query(min_length=1, max_length=200)],
    request: Request,
) -> ConversationHistoryResponse:
    return await _service(request).get_conversation_history(
        user_id=user_id,
        thread_id=thread_id,
    )
