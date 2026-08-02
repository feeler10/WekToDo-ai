from app.graph.state import TaskAgentState
from app.services.task_reference import parse_status_update


def parse_task_reference(state: TaskAgentState) -> dict[str, object]:
    try:
        parsed = parse_status_update(state.get('user_message', ''))
    except Exception as exc:
        return {'error_message': f'Task reference parsing failed: {exc}'}
    return {
        'task_reference': parsed.reference,
        'target_status': parsed.target_status.value,
        'error_message': None,
    }
