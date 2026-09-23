from typing import Annotated

from fastapi import APIRouter, Path, Query, Request

from app.core.exceptions import AppError
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest, AgentResponse
from app.schemas.conversation import ConversationHistoryResponse
from app.schemas.trace import TraceDetailResponse
from app.services.agent import (
    AgentThreadConflictError,
    AgentThreadNotFoundError,
    AgentTraceNotFoundError,
    TaskAgentService,
)

router = APIRouter(prefix='/api/agent', tags=['agent'])


def _service(request: Request) -> TaskAgentService:
    service = getattr(request.app.state, 'agent_service', None)
    if service is None:
        raise AppError(
            '任务助手服务暂时不可用，请稍后重试。',
            code='agent_unavailable',
            status_code=503,
        )
    return service


@router.post('/chat', response_model=AgentResponse)
async def chat(payload: AgentChatRequest, request: Request) -> AgentResponse:
    try:
        response = await _service(request).chat(payload)
        request.state.trace_id = response.trace_id
        return response
    except AgentThreadConflictError as exc:
        raise AppError(
            '当前会话正在等待确认，请先完成或取消待确认操作。',
            code='thread_conflict',
            status_code=409,
        ) from exc


@router.post('/confirm', response_model=AgentResponse)
async def confirm(payload: AgentConfirmRequest, request: Request) -> AgentResponse:
    try:
        response = await _service(request).confirm(payload)
        request.state.trace_id = response.trace_id
        return response
    except AgentThreadNotFoundError as exc:
        raise AppError(
            '没有找到可恢复的会话或待确认操作。',
            code='thread_not_found',
            status_code=404,
        ) from exc
    except AgentThreadConflictError as exc:
        raise AppError(
            '确认操作与当前会话状态不一致，请刷新后重试。',
            code='thread_conflict',
            status_code=409,
        ) from exc


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


@router.get('/traces/{trace_id}', response_model=TraceDetailResponse)
async def get_trace(
    trace_id: Annotated[str, Path(min_length=1, max_length=100)],
    user_id: Annotated[str, Query(min_length=1, max_length=200)],
    request: Request,
) -> TraceDetailResponse:
    try:
        response = await _service(request).get_trace(
            user_id=user_id,
            trace_id=trace_id,
        )
        return response
    except AgentTraceNotFoundError as exc:
        raise AppError(
            '没有找到该追踪记录或你无权访问。',
            code='trace_not_found',
            status_code=404,
        ) from exc
