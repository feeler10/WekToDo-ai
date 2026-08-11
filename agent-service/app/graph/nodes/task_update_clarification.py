import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.task import Task
from app.schemas.task_attribute_update import TaskUpdateParseResult
from app.schemas.task_update_context import PendingTaskUpdateClarification
from app.services.task_update_clarification import (
    is_task_update_collection_cancellation,
    looks_like_explicit_new_request,
)
from app.services.pending_operation_logging import log_pending_operation_event


logger = logging.getLogger(__name__)


def prepare_task_update_clarification(
    state: TaskAgentState,
    *,
    clock: Callable[[], datetime],
    pending_ttl: timedelta,
    max_rounds: int,
) -> dict[str, object]:
    try:
        task = Task.model_validate(state.get('selected_task'))
        partial_result = TaskUpdateParseResult.model_validate(
            state.get('task_update_result')
        )
        if not partial_result.needs_clarification:
            raise ValueError('task update result does not need clarification')
        clarification_round = (
            state.get('task_update_clarification_round', 0) + 1
        )
        if clarification_round > max_rounds:
            log_pending_operation_event(
                logger,
                state=state,
                operation_type='task_update',
                event='max_rounds',
                round_number=clarification_round,
                task_id=task.id,
                expected_version=task.version,
                reason='clarification_limit_reached',
                next_node='finalize_turn',
            )
            return {
                'pending_task_update_clarification': None,
                'task_update_inputs': [],
                'task_update_clarification_round': 0,
                'task_update_result': None,
                'task_update': None,
                'confirmation_status': 'rejected',
                'final_response': (
                    '多轮补充后仍无法形成明确的任务修改，'
                    '本次修改已停止。请重新完整说明要修改的字段和新值。'
                ),
                'error_message': None,
            }
        user_inputs = list(state.get('task_update_inputs') or [])
        if not user_inputs:
            user_inputs = [
                state.get('task_update_message')
                or state.get('user_message', '')
            ]
        now = clock()
        pending = PendingTaskUpdateClarification(
            user_id=state['user_id'],
            thread_id=state['thread_id'],
            user_inputs=user_inputs,
            task_id=task.id,
            expected_version=task.version,
            partial_result=partial_result,
            clarification_question=(
                partial_result.clarification_question or '请补充修改内容。'
            ),
            clarification_round=clarification_round,
            created_at=now,
            expires_at=now + pending_ttl,
        )
    except Exception as exc:
        return {
            'error_message': (
                f'Could not prepare task update clarification: {exc}'
            )
        }
    log_pending_operation_event(
        logger,
        state=state,
        operation_type='task_update',
        event='prepared',
        round_number=clarification_round,
        task_id=task.id,
        expected_version=task.version,
        next_node='finalize_turn',
        expires_at=pending.expires_at,
    )
    return {
        'pending_task_update_clarification': pending.model_dump(mode='json'),
        'task_update_inputs': user_inputs,
        'task_update_clarification_round': clarification_round,
        'final_response': pending.clarification_question,
        'error_message': None,
    }


async def resolve_task_update_clarification(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    pending = PendingTaskUpdateClarification.model_validate(
        state.get('pending_task_update_clarification')
    )
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('clock must return a timezone-aware datetime')
    message = state.get('user_message', '')
    cleared = {
        'pending_task_update_clarification': None,
        'task_update_inputs': [],
        'task_update_clarification_round': 0,
    }
    if pending.expires_at <= now:
        log_pending_operation_event(
            logger,
            state=state,
            operation_type='task_update',
            event='expired',
            round_number=pending.clarification_round,
            task_id=pending.task_id,
            expected_version=pending.expected_version,
            reason='context_ttl_elapsed',
            next_node='classify_intent',
            expires_at=pending.expires_at,
        )
        return {**cleared, 'pending_route': 'classify'}
    if is_task_update_collection_cancellation(message):
        log_pending_operation_event(
            logger,
            state=state,
            operation_type='task_update',
            event='cancelled',
            round_number=pending.clarification_round,
            task_id=pending.task_id,
            expected_version=pending.expected_version,
            reason='explicit_user_cancellation',
            next_node='finalize_turn',
        )
        return {
            **cleared,
            'pending_route': 'handled',
            'confirmation_status': 'rejected',
            'final_response': '已取消本次任务修改。',
            'error_message': None,
        }
    if looks_like_explicit_new_request(message):
        log_pending_operation_event(
            logger,
            state=state,
            operation_type='task_update',
            event='replaced',
            round_number=pending.clarification_round,
            task_id=pending.task_id,
            expected_version=pending.expected_version,
            reason='explicit_new_operation',
            next_node='classify_intent',
        )
        return {
            **cleared,
            'pending_route': 'classify',
            'final_response': None,
            'error_message': None,
        }
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        task = await repository.get(
            user_id=state['user_id'],
            task_id=pending.task_id,
        )
    except Exception as exc:
        return {'error_message': f'Task update context restore failed: {exc}'}
    if task is None or task.version != pending.expected_version:
        log_pending_operation_event(
            logger,
            state=state,
            operation_type='task_update',
            event='stale',
            round_number=pending.clarification_round,
            task_id=pending.task_id,
            expected_version=pending.expected_version,
            reason='task_missing_or_version_changed',
            next_node='finalize_turn',
        )
        return {
            **cleared,
            'pending_route': 'handled',
            'confirmation_status': 'rejected',
            'final_response': (
                '目标任务已被删除或在补充期间发生变化，'
                '本次修改已停止，请重新发起。'
            ),
            'error_message': None,
        }
    log_pending_operation_event(
        logger,
        state=state,
        operation_type='task_update',
        event='resumed',
        round_number=pending.clarification_round,
        task_id=pending.task_id,
        expected_version=pending.expected_version,
        next_node='parse_task_update',
    )
    return {
        'pending_task_update_clarification': None,
        'task_update_inputs': [*pending.user_inputs, message],
        'task_update_clarification_round': pending.clarification_round,
        'pending_route': 'task_update_resume',
        'selected_task': task.model_dump(mode='json'),
        'task_update_result': pending.partial_result.model_dump(mode='json'),
        'task_update': None,
        'task_update_message': None,
        'final_response': None,
        'error_message': None,
    }
