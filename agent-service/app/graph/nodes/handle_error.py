from app.graph.state import TaskAgentState


def handle_error(state: TaskAgentState) -> dict[str, str]:
    message = state.get('error_message')
    if not message:
        intent = state.get('intent', 'UNKNOWN')
        message = f'Intent is not supported by the minimal graph: {intent}'
    return {
        'error_message': message,
        'final_response': message,
    }
