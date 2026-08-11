import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from app.graph.state import TaskAgentState
from app.schemas.draft import TaskDraftCandidate, TaskDraftFieldName
from app.schemas.task_draft_context import PendingTaskDraftClarification
from app.services.task_draft_clarification import (
    format_task_draft_clarification,
    is_task_draft_collection_cancellation,
    looks_like_explicit_new_request,
)


logger = logging.getLogger(__name__)


def prepare_task_draft_clarification(
    state: TaskAgentState,
    *,
    clock: Callable[[], datetime],
    pending_ttl: timedelta,
    max_rounds: int,
) -> dict[str, object]:
    candidate = TaskDraftCandidate.model_validate(state.get('task_draft'))
    missing_fields = [
        TaskDraftFieldName(field) for field in state.get('missing_fields', [])
    ]
    clarification_round = state.get('task_draft_clarification_round', 0) + 1
    if clarification_round > max_rounds:
        return {
            'pending_task_draft_clarification': None,
            'task_collection_inputs': [],
            'task_draft_clarification_round': 0,
            'confirmation_status': 'rejected',
            'final_response': (
                '多轮补充后仍无法形成完整任务草稿，本次创建已停止。'
                '请重新完整描述任务名称和必要信息。'
            ),
            'error_message': None,
        }

    now = clock()
    question = format_task_draft_clarification(candidate, missing_fields)
    pending = PendingTaskDraftClarification(
        user_id=state['user_id'],
        thread_id=state['thread_id'],
        user_inputs=list(state.get('task_collection_inputs') or []),
        partial_draft=candidate,
        missing_fields=missing_fields,
        clarification_question=question,
        clarification_round=clarification_round,
        created_at=now,
        expires_at=now + pending_ttl,
    )
    logger.info(
        'pending_state_type=task_draft_clarification request_id=%s '
        'user_id=%s thread_id=%s round=%s missing_fields=%s '
        'pending_expires_at=%s',
        state.get('request_id'),
        state.get('user_id'),
        state.get('thread_id'),
        clarification_round,
        [field.value for field in missing_fields],
        pending.expires_at.isoformat(),
    )
    return {
        'pending_task_draft_clarification': pending.model_dump(mode='json'),
        'task_draft_clarification_round': clarification_round,
        'final_response': question,
        'error_message': None,
    }


def resolve_task_draft_clarification(
    state: TaskAgentState,
    *,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    pending = PendingTaskDraftClarification.model_validate(
        state.get('pending_task_draft_clarification')
    )
    now = clock()
    message = state.get('user_message', '')
    if pending.expires_at <= now:
        return {
            'pending_task_draft_clarification': None,
            'task_collection_inputs': [],
            'task_draft_clarification_round': 0,
            'pending_route': 'classify',
        }
    if is_task_draft_collection_cancellation(message):
        return {
            'pending_task_draft_clarification': None,
            'task_collection_inputs': [],
            'task_draft_clarification_round': 0,
            'pending_route': 'handled',
            'confirmation_status': 'rejected',
            'final_response': '已取消本次任务创建。',
            'error_message': None,
        }
    if looks_like_explicit_new_request(message):
        return {
            'pending_task_draft_clarification': None,
            'task_collection_inputs': [],
            'task_draft_clarification_round': 0,
            'pending_route': 'classify',
            'final_response': None,
            'error_message': None,
        }
    return {
        'pending_task_draft_clarification': None,
        'task_collection_inputs': [*pending.user_inputs, message],
        'task_draft_clarification_round': pending.clarification_round,
        'pending_route': 'draft_resume',
        'task_draft': pending.partial_draft.model_dump(mode='json'),
        'final_response': None,
        'error_message': None,
    }
