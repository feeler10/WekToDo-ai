from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.audit import PendingAction
from app.schemas.task import TaskStatusUpdate
from app.tools.task_tools import update_task_status_with_rollup
from app.services.task_response import format_status_update_result
from app.services.error_mapping import error_state
from app.services.observability import ObservabilityService, execute_observed_tool


async def execute_status_update(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    observability: ObservabilityService | None = None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        pending = PendingAction.model_validate(state.get('pending_action'))
        payload = TaskStatusUpdate.model_validate(pending.payload)
        if pending.target_id is None:
            raise ValueError('Status update target_id is required')
        confirmed = pending.confirmation_status == 'approved'
        result = await execute_observed_tool(
            observability,
            state=state,
            tool_name='update_task_status_with_rollup',
            input_payload=pending.payload,
            confirmed=confirmed,
            idempotency_key=pending.idempotency_key,
            action_id=pending.id,
            operation=lambda: update_task_status_with_rollup(
                repository=repository,
                user_id=payload.user_id,
                task_id=pending.target_id or '',
                target_status=payload.target_status,
                expected_version=payload.expected_version,
                confirmed_reopen=payload.confirmed_reopen,
                confirmed_restore=payload.confirmed_restore,
                idempotency_key=pending.idempotency_key,
                confirmed=confirmed,
            ),
        )
        task = result.task
    except Exception as exc:
        return error_state(exc, trace_id=state.get('trace_id'))
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
