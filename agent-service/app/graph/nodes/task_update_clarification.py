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
    logger.info(
        'pending_state_type=task_update_clarification request_id=%s '
        'user_id=%s thread_id=%s task_id=%s expected_version=%s round=%s '
        'pending_expires_at=%s',
        state.get('request_id'),
        state.get('user_id'),
        state.get('thread_id'),
        task.id,
        task.version,
        clarification_round,
        pending.expires_at.isoformat(),
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
        return {**cleared, 'pending_route': 'classify'}
    if is_task_update_collection_cancellation(message):
        return {
            **cleared,
            'pending_route': 'handled',
            'confirmation_status': 'rejected',
            'final_response': '已取消本次任务修改。',
            'error_message': None,
        }
    if looks_like_explicit_new_request(message):
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
