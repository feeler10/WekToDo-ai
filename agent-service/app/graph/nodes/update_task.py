from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.audit import PendingAction
from app.schemas.task import TaskUpdate
from app.services.task_response import format_task_update_result
from app.tools.task_tools import update_task


async def execute_task_update(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        pending = PendingAction.model_validate(state.get('pending_action'))
        if pending.target_id is None:
            raise ValueError('Task update target_id is required')
        payload = TaskUpdate.model_validate(pending.payload)
        task = await update_task(
            repository=repository,
            user_id=payload.user_id,
            task_id=pending.target_id,
            update=payload,
            idempotency_key=pending.idempotency_key,
            confirmed=pending.confirmation_status == 'approved',
        )
    except Exception as exc:
        return {'error_message': f'Task update failed: {exc}'}
    return {
        'updated_task': task.model_dump(mode='json'),
        'selected_task': task.model_dump(mode='json'),
        'final_response': format_task_update_result(task),
        'error_message': None,
    }
