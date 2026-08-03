import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from app.intent.enums import IntentType
from app.graph.state import TaskAgentState
from app.matching.base import TaskMatcher
from app.repositories.base import TaskRepository
from app.schemas.task import TaskQuery
from app.schemas.query_context import PendingTaskSelection
from app.services.task_response import (
    format_multiple_matches_response,
    format_zero_match_response,
)
from app.tools.task_tools import query_tasks
logger = logging.getLogger(__name__)



async def resolve_task_reference(
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
        now = clock()
        result = await query_tasks(
            repository=repository,
            query=TaskQuery(user_id=state['user_id'], limit=100),
        )
        matched = task_matcher.match(
            reference=state.get('task_reference', ''),
            user_id=state['user_id'],
            tasks=result.items,
        )
    except Exception as exc:
        return {'error_message': f'Task reference resolution failed: {exc}'}

    serialized = [
        task.model_dump(mode='json') for task in matched.tasks
    ]
    if not serialized:
        return {
            'candidate_tasks': [],
            'selected_task': None,
            'pending_task_selection': None,
            'final_response': format_zero_match_response(
                plan=None,
                reference=state.get('task_reference'),
            ),
            'error_message': None,
        }
    if len(serialized) > 1:
        pending = PendingTaskSelection(
            user_id=state['user_id'],
            thread_id=state['thread_id'],
            operation=IntentType.UPDATE_TASK_STATUS,
            candidate_task_ids=[task.id for task in matched.tasks],
            candidate_versions={
                task.id: task.version for task in matched.tasks
            },
            reference=state.get('task_reference') or '候选任务',
            target_status=state.get('target_status'),
            created_at=now,
            expires_at=now + pending_ttl,
        )
        logger.info(
            'pending_state_type=task_selection request_id=%s user_id=%s '
            'thread_id=%s candidate_count=%s operation=%s '
            'pending_created_at=%s pending_expires_at=%s',
            state.get('request_id'),
            state.get('user_id'),
            state.get('thread_id'),
            len(matched.tasks),
            IntentType.UPDATE_TASK_STATUS.value,
            pending.created_at.isoformat(),
            pending.expires_at.isoformat(),
        )
        return {
            'candidate_tasks': serialized,
            'selected_task': None,
            'pending_task_selection': pending.model_dump(mode='json'),
            'final_response': (
                format_multiple_matches_response(
                    reference=pending.reference,
                    tasks=matched.tasks,
                    timezone_name=state.get('timezone', 'UTC'),
                    operation_label='更新',
                )
            ),
            'error_message': None,
        }
    return {
        'candidate_tasks': [],
        'selected_task': serialized[0],
        'pending_task_selection': None,
        'final_response': None,
        'error_message': None,
    }
