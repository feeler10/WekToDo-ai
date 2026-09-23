from app.graph.state import TaskAgentState
from app.schemas.errors import AgentErrorInfo
from app.services.error_mapping import map_legacy_graph_error


def handle_error(state: TaskAgentState) -> dict[str, object]:
    existing = state.get('error')
    error = (
        AgentErrorInfo.model_validate(existing)
        if existing
        else map_legacy_graph_error(
            state.get('error_message'),
            trace_id=state.get('trace_id'),
        )
    )
    return {
        'error': error.model_dump(mode='json'),
        'error_message': error.message,
        'final_response': error.message,
    }
