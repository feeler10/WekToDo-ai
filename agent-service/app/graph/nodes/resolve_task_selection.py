import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from app.graph.state import TaskAgentState
from app.intent.enums import IntentType
from app.repositories.base import TaskRepository
from app.schemas.query_context import PendingTaskSelection
from app.schemas.task import Task
from app.services.task_response import (
    format_cancelled_response,
    format_multiple_matches_response,
    format_selection_error,
    format_stale_candidate_response,
    format_task_detail_response,
    format_subtask_list_response,
)
from app.services.task_selection import (
    TaskSelectionError,
    is_pending_cancellation,
    looks_like_new_request,
    ordered_available_tasks,
    parse_candidate_selection,
    refreshed_pending_selection,
)
from app.services.task_state import validate_status_transition

logger = logging.getLogger(__name__)


async def resolve_task_selection(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    pending = PendingTaskSelection.model_validate(
        state.get('pending_task_selection')
    )
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('clock must return a timezone-aware datetime')
    if pending.expires_at <= now:
        logger.info(
            'Pending selection expired user_id=%s thread_id=%s',
            state.get('user_id'),
            state.get('thread_id'),
        )
        return {
            'pending_task_selection': None,
            'candidate_tasks': [],
            'pending_route': 'classify',
        }

    message = state.get('user_message', '')
    if is_pending_cancellation(message):
        return {
            'pending_task_selection': None,
            'candidate_tasks': [],
            'pending_route': 'handled',
            'final_response': format_cancelled_response('任务选择'),
            'error_message': None,
        }

    try:
        loaded = await asyncio.gather(
            *(
                repository.get(
                    user_id=state['user_id'],
                    task_id=task_id,
                )
                for task_id in pending.candidate_task_ids
            )
        )
    except Exception as exc:
        return {'error_message': f'读取候选任务失败：{exc}'}

    tasks_by_id: dict[str, Task] = {
        task.id: task for task in loaded if task is not None
    }
    try:
        selected_id = parse_candidate_selection(
            message=message,
            pending=pending,
            tasks_by_id=tasks_by_id,
        )
    except TaskSelectionError as exc:
        available = ordered_available_tasks(pending, tasks_by_id)
        if looks_like_new_request(message):
            return {
                'pending_task_selection': None,
                'candidate_tasks': [],
                'pending_route': 'classify',
            }
        if not available:
            return {
                'pending_task_selection': None,
                'candidate_tasks': [],
                'pending_route': 'handled',
                'final_response': format_stale_candidate_response(),
                'error_message': None,
            }
        refreshed = refreshed_pending_selection(pending, available)
        candidates = [
            task.model_dump(mode='json') for task in available
        ]
        return {
            'pending_task_selection': refreshed.model_dump(mode='json'),
            'candidate_tasks': candidates,
            'pending_route': 'handled',
            'final_response': (
                format_selection_error(str(exc))
                + '\n\n'
                + format_multiple_matches_response(
                    reference=pending.reference,
                    tasks=available,
                    timezone_name=state.get('timezone', 'UTC'),
                    operation_label=(
                        '查看'
                        if pending.operation == IntentType.QUERY_TASKS
                        else (
                            '拆解'
                            if pending.operation == IntentType.DECOMPOSE_TASK
                            else '更新'
                        )
                    ),
                )
            ),
            'error_message': None,
        }

    selected = tasks_by_id.get(selected_id)
    expected_version = pending.candidate_versions.get(selected_id)
    if selected is None or selected.version != expected_version:
        logger.info(
            'Selected candidate stale user_id=%s thread_id=%s task_id=%s',
            state.get('user_id'),
            state.get('thread_id'),
            selected_id,
        )
        return {
            'pending_task_selection': None,
            'candidate_tasks': [],
            'pending_route': 'handled',
            'final_response': format_stale_candidate_response(),
            'error_message': None,
        }

    serialized = selected.model_dump(mode='json')
    if pending.operation == IntentType.QUERY_TASKS:
        if pending.include_subtasks:
            try:
                subtasks = await repository.list_children(
                    user_id=state['user_id'],
                    parent_id=selected.id,
                )
            except Exception as exc:
                return {'error_message': f'读取子任务失败：{exc}'}
            final_response = format_subtask_list_response(
                selected,
                subtasks,
                timezone_name=state.get('timezone', 'UTC'),
            )
        else:
            final_response = format_task_detail_response(
                selected,
                timezone_name=state.get('timezone', 'UTC'),
            )
        return {
            'pending_task_selection': None,
            'candidate_tasks': [],
            'selected_task': serialized,
            'task_results': [serialized],
            'pending_route': 'handled',
            'final_response': final_response,
            'error_message': None,
        }

    if pending.operation == IntentType.UPDATE_TASK:
        return {
            'pending_task_selection': None,
            'candidate_tasks': [],
            'selected_task': serialized,
            'task_update_message': pending.task_update_message,
            'pending_route': 'selected_attribute_update',
            'final_response': None,
            'error_message': None,
        }

    if pending.operation == IntentType.DECOMPOSE_TASK:
        return {
            'pending_task_selection': None,
            'candidate_tasks': [],
            'selected_task': serialized,
            'decomposition_message': pending.decomposition_message,
            'pending_route': 'selected_decomposition',
            'final_response': None,
            'error_message': None,
        }

    assert pending.target_status is not None
    confirmed_reopen = (
        selected.status.value == 'DONE'
        and pending.target_status.value == 'DOING'
    )
    try:
        validate_status_transition(
            selected.status,
            pending.target_status,
            confirmed_reopen=confirmed_reopen,
        )
    except ValueError:
        return {
            'pending_task_selection': None,
            'candidate_tasks': [],
            'pending_route': 'handled',
            'final_response': '该任务当前状态已不允许执行原更新，请重新发起请求。',
            'error_message': None,
        }

    return {
        'pending_task_selection': None,
        'candidate_tasks': [],
        'selected_task': serialized,
        'target_status': pending.target_status.value,
        'pending_route': 'selected_update',
        'final_response': None,
        'error_message': None,
    }
