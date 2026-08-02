from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.audit import PendingAction
from app.schemas.task import TaskStatusUpdate
from app.tools.task_tools import update_task_status


async def execute_status_update(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        pending = PendingAction.model_validate(state.get('pending_action'))
        payload = TaskStatusUpdate.model_validate(pending.payload)
        if pending.target_id is None:
            raise ValueError('Status update target_id is required')
        task = await update_task_status(
            repository=repository,
            user_id=payload.user_id,
            task_id=pending.target_id,
            target_status=payload.target_status,
            expected_version=payload.expected_version,
            confirmed_reopen=payload.confirmed_reopen,
            idempotency_key=pending.idempotency_key,
            confirmed=pending.confirmation_status == 'approved',
        )
    except Exception as exc:
        return {'error_message': f'Task status update failed: {exc}'}
    return {
        'updated_task': task.model_dump(mode='json'),
        'selected_task': task.model_dump(mode='json'),
        'final_response': f'Task status updated to {task.status.value}: {task.title}',
        'error_message': None,
    }
