from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.audit import PendingAction
from app.schemas.task import TaskStatusUpdate
from app.tools.task_tools import update_task_status_with_rollup
from app.services.task_response import format_status_update_result


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
        result = await update_task_status_with_rollup(
            repository=repository,
            user_id=payload.user_id,
            task_id=pending.target_id,
            target_status=payload.target_status,
            expected_version=payload.expected_version,
            confirmed_reopen=payload.confirmed_reopen,
            idempotency_key=pending.idempotency_key,
            confirmed=pending.confirmation_status == 'approved',
        )
        task = result.task
    except Exception as exc:
        return {'error_message': f'Task status update failed: {exc}'}
    message = format_status_update_result(task)
    if result.parent_task is not None:
        if result.parent_task.status.value == 'DONE':
            message += f' 父任务“{result.parent_task.title}”已自动完成。'
        else:
            message += (
                f' 父任务“{result.parent_task.title}”进度已更新为'
                f'{result.parent_task.progress}%。'
            )
    return {
        'updated_task': task.model_dump(mode='json'),
        'selected_task': task.model_dump(mode='json'),
        'parent_task': (
            result.parent_task.model_dump(mode='json')
            if result.parent_task is not None
            else None
        ),
        'final_response': message,
        'error_message': None,
    }
