from collections.abc import Callable
from datetime import datetime

from app.graph.state import TaskAgentState
from app.intent.enums import IntentType, TimeScope
from app.intent.models import IntentResult
from app.matching.base import TaskMatcher
from app.repositories.base import TaskRepository
from app.schemas.task import Task, TaskQuery
from app.schemas.task_operation import TaskQueryKind
from app.services.task_query_plan import (
    build_task_query_plan,
    task_query_from_plan,
)
from app.tools.task_tools import query_tasks


async def query_task_data(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    task_matcher: TaskMatcher,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        intent_result = IntentResult.model_validate(state.get('intent_result'))
        if intent_result.intent != IntentType.QUERY_TASKS:
            raise ValueError('QUERY_TASKS intent result is required')
        query_intent = intent_result.query
        if query_intent is None:
            raise ValueError('Task query intent is missing')
        user_id = state['user_id']
        plan = None
        if query_intent.time_scope == TimeScope.UNSPECIFIED:
            if intent_result.task_reference is None:
                raise ValueError('UNSPECIFIED is not executable')
            repository_query = TaskQuery(
                user_id=user_id,
                statuses=query_intent.statuses,
                priorities=query_intent.priorities,
                limit=100,
            )
        else:
            plan = build_task_query_plan(
                intent_result=intent_result,
                user_id=user_id,
                timezone_name=state.get('timezone', 'UTC'),
                now=clock(),
            )
            repository_query = task_query_from_plan(plan)

        result = await query_tasks(
            repository=repository,
            query=repository_query,
        )
        serialized_plan = (
            plan.model_dump(mode='json') if plan is not None else None
        )
        if intent_result.task_reference is not None:
            matched = task_matcher.match(
                reference=intent_result.task_reference,
                user_id=user_id,
                tasks=result.items,
            )
            return _match_result(
                matched.tasks,
                query_plan=serialized_plan,
            )
    except Exception as exc:
        return {'error_message': f'Task query failed: {exc}'}

    items = [task.model_dump(mode='json') for task in result.items]
    return {
        'query_kind': TaskQueryKind.LIST.value,
        'task_query_plan': serialized_plan,
        'task_results': items,
        'candidate_tasks': [],
        'selected_task': None,
        'final_response': f'Found {result.total} task(s)',
        'error_message': None,
    }


def _match_result(
    candidates: list[Task],
    *,
    query_plan: dict[str, object] | None,
) -> dict[str, object]:
    serialized = [
        candidate.model_dump(mode='json')
        for candidate in candidates
    ]
    if len(serialized) == 1:
        selected = serialized[0]
        return {
            'query_kind': TaskQueryKind.DETAIL.value,
            'task_query_plan': query_plan,
            'task_results': serialized,
            'candidate_tasks': [],
            'selected_task': selected,
            'final_response': f"Task detail: {selected['title']}",
            'error_message': None,
        }
    message = (
        'Task not found' if not serialized
        else 'Multiple tasks matched; specify a task id or exact title'
    )
    return {
        'query_kind': TaskQueryKind.DETAIL.value,
        'task_query_plan': query_plan,
        'task_results': [],
        'candidate_tasks': serialized,
        'selected_task': None,
        'final_response': message,
        'error_message': None,
    }
