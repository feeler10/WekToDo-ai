from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.audit import PendingAction
from app.tools.task_tools import create_task
from app.services.error_mapping import error_state
from app.services.observability import ObservabilityService, execute_observed_tool


async def execute_create_task(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    observability: ObservabilityService | None = None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}

    try:
        pending = PendingAction.model_validate(state.get('pending_action'))
        confirmed = pending.confirmation_status == 'approved'
        task = await execute_observed_tool(
            observability,
            state=state,
            tool_name='create_task',
            input_payload=pending.payload,
            confirmed=confirmed,
            idempotency_key=pending.idempotency_key,
            action_id=pending.id,
            operation=lambda: create_task(
                repository=repository,
                task_input=pending.payload,
                idempotency_key=pending.idempotency_key,
                confirmed=confirmed,
            ),
        )
    except Exception as exc:
        return error_state(exc, trace_id=state.get('trace_id'))

    return {
        'created_task': task.model_dump(mode='json'),
        'final_response': f'已创建任务“{task.title}”。',
        'error_message': None,
    }
