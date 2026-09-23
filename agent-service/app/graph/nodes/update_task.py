from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.audit import PendingAction
from app.schemas.task import TaskUpdate
from app.services.task_response import format_task_update_result
from app.tools.task_tools import update_task
from app.services.error_mapping import error_state
from app.services.observability import ObservabilityService, execute_observed_tool


async def execute_task_update(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    observability: ObservabilityService | None = None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        pending = PendingAction.model_validate(state.get('pending_action'))
        if pending.target_id is None:
            raise ValueError('Task update target_id is required')
        payload = TaskUpdate.model_validate(pending.payload)
        confirmed = pending.confirmation_status == 'approved'
        task = await execute_observed_tool(
            observability,
            state=state,
            tool_name='update_task',
            input_payload={
                **pending.payload,
                'field_names': sorted(
                    key
                    for key in pending.payload
                    if key not in {'user_id', 'expected_version'}
                ),
            },
            confirmed=confirmed,
            idempotency_key=pending.idempotency_key,
            action_id=pending.id,
            operation=lambda: update_task(
                repository=repository,
                user_id=payload.user_id,
                task_id=pending.target_id or '',
                update=payload,
                idempotency_key=pending.idempotency_key,
                confirmed=confirmed,
            ),
        )
    except Exception as exc:
        return error_state(exc, trace_id=state.get('trace_id'))
    return {
        'updated_task': task.model_dump(mode='json'),
        'selected_task': task.model_dump(mode='json'),
        'final_response': format_task_update_result(task),
        'error_message': None,
    }
