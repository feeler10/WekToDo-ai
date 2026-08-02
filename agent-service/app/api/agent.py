from fastapi import APIRouter, Request

from app.core.exceptions import AppError
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest, AgentResponse
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
