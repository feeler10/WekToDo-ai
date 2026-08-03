import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from app.graph.state import TaskAgentState
from app.intent.enums import ClarificationReason, IntentType
from app.intent.models import IntentResult
from app.schemas.query_context import (
    PendingQueryClarification,
    missing_fields_for_reason,
)
from app.services.task_response import format_query_clarification

logger = logging.getLogger(__name__)


def request_intent_clarification(
    state: TaskAgentState,
    *,
    clock: Callable[[], datetime],
    pending_ttl: timedelta,
) -> dict[str, object]:
    result = IntentResult.model_validate(state.get('intent_result'))
    pending = None
    reason = result.clarification_reason
    if result.intent == IntentType.QUERY_TASKS:
        reason = reason or ClarificationReason.UNRESOLVED_CONTEXT
        now = clock()
        pending = PendingQueryClarification(
            user_id=state['user_id'],
            thread_id=state['thread_id'],
            original_intent=result,
            clarification_reason=reason,
            missing_fields=missing_fields_for_reason(reason),
            created_at=now,
            expires_at=now + pending_ttl,
        )
        logger.info(
            'pending_state_type=query_clarification request_id=%s '
            'user_id=%s thread_id=%s clarification_reason=%s '
            'missing_fields=%s pending_created_at=%s '
            'pending_expires_at=%s',
            state.get('request_id'),
            state.get('user_id'),
            state.get('thread_id'),
            reason.value,
            pending.missing_fields,
            pending.created_at.isoformat(),
            pending.expires_at.isoformat(),
        )
    return {
        'pending_query_clarification': (
            pending.model_dump(mode='json') if pending else None
        ),
        'final_response': (
            format_query_clarification(
                reason=reason,
                question=result.clarification_question,
            )
            if reason is not None
            else result.clarification_question
        ),
        'error_message': None,
    }


def respond_to_general_chat(state: TaskAgentState) -> dict[str, object]:
    return {
        'final_response': (
            '你好！我可以帮你创建、查询、修改、完成或拆解任务。'
        ),
        'error_message': None,
    }


def respond_feature_unavailable(state: TaskAgentState) -> dict[str, object]:
    intent = IntentType(state['intent'])
    feature = (
        '任务属性修改'
        if intent == IntentType.UPDATE_TASK
        else '任务拆解'
    )
    return {
        'final_response': f'{feature}功能暂未开放。',
        'error_message': None,
    }


def respond_unknown_intent(state: TaskAgentState) -> dict[str, object]:
    result = IntentResult.model_validate(state.get('intent_result'))
    message = (
        '意图识别服务暂时不可用，请稍后重试。'
        if result.reason == '意图识别服务暂时不可用'
        else '暂时无法识别你的操作，请换一种说法。'
    )
    return {'final_response': message, 'error_message': None}
