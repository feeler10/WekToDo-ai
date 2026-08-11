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
from app.services.pending_operation_logging import log_pending_operation_event


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
        log_pending_operation_event(
            logger,
            state=state,
            operation_type='task_create',
            event='max_rounds',
            round_number=clarification_round,
            missing_fields=[field.value for field in missing_fields],
            reason='clarification_limit_reached',
            next_node='finalize_turn',
        )
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
    log_pending_operation_event(
        logger,
        state=state,
        operation_type='task_create',
        event='prepared',
        round_number=clarification_round,
        missing_fields=[field.value for field in missing_fields],
        next_node='finalize_turn',
        expires_at=pending.expires_at,
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
        log_pending_operation_event(
            logger,
            state=state,
            operation_type='task_create',
            event='expired',
            round_number=pending.clarification_round,
            reason='context_ttl_elapsed',
            next_node='classify_intent',
            expires_at=pending.expires_at,
        )
        return {
            'pending_task_draft_clarification': None,
            'task_collection_inputs': [],
            'task_draft_clarification_round': 0,
            'pending_route': 'classify',
        }
    if is_task_draft_collection_cancellation(message):
        log_pending_operation_event(
            logger,
            state=state,
            operation_type='task_create',
            event='cancelled',
            round_number=pending.clarification_round,
            reason='explicit_user_cancellation',
            next_node='finalize_turn',
        )
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
        log_pending_operation_event(
            logger,
            state=state,
            operation_type='task_create',
            event='replaced',
            round_number=pending.clarification_round,
            reason='explicit_new_operation',
            next_node='classify_intent',
        )
        return {
            'pending_task_draft_clarification': None,
            'task_collection_inputs': [],
            'task_draft_clarification_round': 0,
            'pending_route': 'classify',
            'final_response': None,
            'error_message': None,
        }
    log_pending_operation_event(
        logger,
        state=state,
        operation_type='task_create',
        event='resumed',
        round_number=pending.clarification_round,
        next_node='parse_task',
    )
    return {
        'pending_task_draft_clarification': None,
        'task_collection_inputs': [*pending.user_inputs, message],
        'task_draft_clarification_round': pending.clarification_round,
        'pending_route': 'draft_resume',
        'task_draft': pending.partial_draft.model_dump(mode='json'),
        'final_response': None,
        'error_message': None,
    }
