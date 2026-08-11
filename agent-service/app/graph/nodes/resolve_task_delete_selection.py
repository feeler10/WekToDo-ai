import asyncio
from collections.abc import Callable
from datetime import datetime

from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.task import Task
from app.schemas.task_deletion import PendingTaskDeleteSelection
from app.services.task_response import (
    format_cancelled_response,
    format_multiple_matches_response,
    format_selection_error,
    format_stale_candidate_response,
)
from app.services.task_selection import (
    TaskSelectionError,
    is_pending_cancellation,
    looks_like_new_request,
    ordered_available_tasks,
    parse_candidate_selection,
)


async def resolve_task_delete_selection(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    pending = PendingTaskDeleteSelection.model_validate(
        state.get('pending_task_delete_selection')
    )
    now = clock()
    if pending.expires_at <= now:
        return {
            'pending_task_delete_selection': None,
            'candidate_tasks': [],
            'task_delete_selection_route': 'end',
            'final_response': '删除任务选择已过期，请重新发起删除请求。',
            'error_message': None,
        }

    message = state.get('user_message', '')
    if is_pending_cancellation(message):
        return {
            'pending_task_delete_selection': None,
            'candidate_tasks': [],
            'task_delete_selection_route': 'end',
            'final_response': format_cancelled_response('删除任务选择'),
            'error_message': None,
        }

    loaded = await asyncio.gather(
        *(
            repository.get(user_id=state['user_id'], task_id=task_id)
            for task_id in pending.candidate_task_ids
        )
    )
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
        if looks_like_new_request(message):
            return {
                'pending_task_delete_selection': None,
                'candidate_tasks': [],
                'task_delete_selection_route': 'classify',
                'error_message': None,
            }
        available = ordered_available_tasks(pending, tasks_by_id)
        if not available:
            return {
                'pending_task_delete_selection': None,
                'candidate_tasks': [],
                'task_delete_selection_route': 'end',
                'final_response': format_stale_candidate_response(),
                'error_message': None,
            }
        return {
            'candidate_tasks': [
                task.model_dump(mode='json') for task in available
            ],
            'task_delete_selection_route': 'end',
            'final_response': (
                format_selection_error(str(exc))
                + '\n\n'
                + format_multiple_matches_response(
                    reference=pending.current_reference,
                    tasks=available,
                    timezone_name=state.get('timezone', 'UTC'),
                    operation_label='删除',
                )
            ),
            'error_message': None,
        }

    selected = tasks_by_id.get(selected_id)
    if (
        selected is None
        or selected.version != pending.candidate_versions.get(selected_id)
    ):
        return {
            'pending_task_delete_selection': None,
            'candidate_tasks': [],
            'task_delete_selection_route': 'end',
            'final_response': format_stale_candidate_response(),
            'error_message': None,
        }

    resolved_references = dict(pending.resolved_references)
    resolved_parent_id = pending.resolved_parent_id
    if pending.selection_kind == 'parent':
        resolved_parent_id = selected.id
    else:
        resolved_references[pending.current_reference] = selected.id

    return {
        'pending_task_delete_selection': None,
        'candidate_tasks': [],
        'task_delete_parse_result': pending.parse_result.model_dump(mode='json'),
        'task_delete_route': 'batch',
        'resolved_delete_parent_id': resolved_parent_id,
        'resolved_delete_references': resolved_references,
        'task_delete_selection_route': 'resume',
        'final_response': None,
        'error_message': None,
    }
