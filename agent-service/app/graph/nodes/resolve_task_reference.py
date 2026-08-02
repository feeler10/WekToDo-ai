from app.graph.state import TaskAgentState
from app.matching.base import TaskMatcher
from app.repositories.base import TaskRepository
from app.schemas.task import TaskQuery
from app.tools.task_tools import query_tasks


async def resolve_task_reference(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    task_matcher: TaskMatcher,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
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
            'final_response': 'Task not found',
            'error_message': None,
        }
    if len(serialized) > 1:
        return {
            'candidate_tasks': serialized,
            'selected_task': None,
            'final_response': (
                'Multiple tasks matched; specify a task id or exact title'
            ),
            'error_message': None,
        }
    return {
        'candidate_tasks': [],
        'selected_task': serialized[0],
        'final_response': None,
        'error_message': None,
    }
