import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from app.graph.state import TaskAgentState
from app.intent.enums import IntentType, TimeScope
from app.intent.models import IntentResult
from app.matching.base import TaskMatcher
from app.repositories.base import TaskRepository
from app.schemas.task import Task, TaskQuery
from app.schemas.query_context import PendingTaskSelection
from app.schemas.task_operation import TaskQueryKind
from app.services.task_query_plan import (
    build_task_query_plan,
    task_query_from_plan,
)
from app.services.task_response import (
    format_multiple_matches_response,
    format_task_detail_response,
    format_task_list_response,
    format_zero_match_response,
)
from app.tools.task_tools import query_tasks
logger = logging.getLogger(__name__)



async def query_task_data(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    task_matcher: TaskMatcher,
    clock: Callable[[], datetime],
    pending_ttl: timedelta,
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
        now = clock()
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
                now=now,
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
                user_id=user_id,
                thread_id=state['thread_id'],
                request_id=state.get('request_id'),
                reference=intent_result.task_reference,
                timezone_name=state.get('timezone', 'UTC'),
                now=now,
                pending_ttl=pending_ttl,
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
        'pending_task_selection': None,
        'final_response': format_task_list_response(
            result.items,
            plan=plan,
            timezone_name=state.get('timezone', 'UTC'),
        ),
        'error_message': None,
    }


def _match_result(
    candidates: list[Task],
    *,
    query_plan: dict[str, object] | None,
    user_id: str,
    thread_id: str,
    request_id: str | None,
    reference: str,
    timezone_name: str,
    now: datetime,
    pending_ttl: timedelta,
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
            'pending_task_selection': None,
            'final_response': format_task_detail_response(
                candidates[0], timezone_name=timezone_name
            ),
            'error_message': None,
        }
    if not candidates:
        pending = None
        message = format_zero_match_response(
            plan=None,
            reference=reference,
        )
    else:
        pending = PendingTaskSelection(
            user_id=user_id,
            thread_id=thread_id,
            operation=IntentType.QUERY_TASKS,
            candidate_task_ids=[task.id for task in candidates],
            candidate_versions={
                task.id: task.version for task in candidates
            },
            query_plan=query_plan,
            reference=reference,
            created_at=now,
            expires_at=now + pending_ttl,
        )
        message = format_multiple_matches_response(
            reference=reference,
            tasks=candidates,
            timezone_name=timezone_name,
            operation_label='查看',
        )
        logger.info(
            'pending_state_type=task_selection request_id=%s user_id=%s '
            'thread_id=%s candidate_count=%s operation=%s '
            'pending_created_at=%s pending_expires_at=%s',
            request_id,
            user_id,
            thread_id,
            len(candidates),
            IntentType.QUERY_TASKS.value,
            pending.created_at.isoformat(),
            pending.expires_at.isoformat(),
        )
    return {
        'query_kind': TaskQueryKind.DETAIL.value,
        'task_query_plan': query_plan,
        'task_results': [],
        'candidate_tasks': serialized,
        'selected_task': None,
        'pending_task_selection': (
            pending.model_dump(mode='json') if pending else None
        ),
        'final_response': message,
        'error_message': None,
    }
