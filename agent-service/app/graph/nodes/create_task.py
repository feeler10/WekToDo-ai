from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.audit import PendingAction
from app.tools.task_tools import create_task


async def execute_create_task(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}

    try:
        pending = PendingAction.model_validate(state.get('pending_action'))
        task = await create_task(
            repository=repository,
            task_input=pending.payload,
            idempotency_key=pending.idempotency_key,
            confirmed=pending.confirmation_status == 'approved',
        )
    except Exception as exc:
        return {'error_message': f'Task creation failed: {exc}'}

    return {
        'created_task': task.model_dump(mode='json'),
        'final_response': f'已创建任务“{task.title}”。',
        'error_message': None,
    }
