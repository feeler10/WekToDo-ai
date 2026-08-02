from collections.abc import Callable
from datetime import datetime

from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.task import Task, TaskQuery
from app.schemas.task_operation import TaskQueryKind
from app.services.task_reference import parse_task_query, resolve_task_candidates
from app.tools.task_tools import (
    get_overdue_tasks,
    get_task_detail,
    get_today_tasks,
    query_tasks,
)


async def query_task_data(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        parsed = parse_task_query(state.get('user_message', ''))
        user_id = state['user_id']
        if parsed.kind == TaskQueryKind.TODAY:
            result = await get_today_tasks(
                repository=repository,
                user_id=user_id,
                timezone_name=state.get('timezone', 'UTC'),
                now=clock(),
            )
        elif parsed.kind == TaskQueryKind.OVERDUE:
            result = await get_overdue_tasks(
                repository=repository,
                user_id=user_id,
                now=clock(),
            )
        elif parsed.kind == TaskQueryKind.DETAIL:
            all_tasks = await query_tasks(
                repository=repository,
                query=TaskQuery(user_id=user_id, limit=100),
            )
            candidates = resolve_task_candidates(
                parsed.reference or '',
                all_tasks.items,
            )
            if len(candidates) != 1:
                return _candidate_result(parsed.kind, candidates)
            detail = await get_task_detail(
                repository=repository,
                user_id=user_id,
                task_id=candidates[0].id,
            )
            result_items = [detail] if detail is not None else []
            return {
                'query_kind': parsed.kind.value,
                'task_results': [
                    task.model_dump(mode='json') for task in result_items
                ],
                'candidate_tasks': [],
                'selected_task': (
                    detail.model_dump(mode='json') if detail is not None else None
                ),
                'final_response': (
                    f'Task detail: {detail.title}'
                    if detail is not None
                    else 'Task not found'
                ),
                'error_message': None,
            }
        else:
            result = await query_tasks(
                repository=repository,
                query=TaskQuery(
                    user_id=user_id,
                    statuses=parsed.statuses,
                    priorities=parsed.priorities,
                    limit=100,
                ),
            )
    except Exception as exc:
        return {'error_message': f'Task query failed: {exc}'}

    items = [task.model_dump(mode='json') for task in result.items]
    return {
        'query_kind': parsed.kind.value,
        'task_results': items,
        'candidate_tasks': [],
        'selected_task': None,
        'final_response': f'Found {result.total} task(s)',
        'error_message': None,
    }


def _candidate_result(
    kind: TaskQueryKind,
    candidates: list[Task],
) -> dict[str, object]:
    serialized = [task.model_dump(mode='json') for task in candidates]
    message = (
        'Task not found'
        if not candidates
        else 'Multiple tasks matched; specify a task id or exact title'
    )
    return {
        'query_kind': kind.value,
        'task_results': [],
        'candidate_tasks': serialized,
        'selected_task': None,
        'final_response': message,
        'error_message': None,
    }
