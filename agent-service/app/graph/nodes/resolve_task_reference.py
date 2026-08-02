from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.task import TaskQuery
from app.services.task_reference import resolve_task_candidates
from app.tools.task_tools import query_tasks


async def resolve_task_reference(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        result = await query_tasks(
            repository=repository,
            query=TaskQuery(user_id=state['user_id'], limit=100),
        )
        candidates = resolve_task_candidates(
            state.get('task_reference', ''),
            result.items,
        )
    except Exception as exc:
        return {'error_message': f'Task reference resolution failed: {exc}'}

    serialized = [task.model_dump(mode='json') for task in candidates]
    if not candidates:
        return {
            'candidate_tasks': [],
            'selected_task': None,
            'final_response': 'Task not found',
            'error_message': None,
        }
    if len(candidates) > 1:
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
