from app.graph.parser import TaskParser
from app.graph.state import TaskAgentState


async def parse_task(
    state: TaskAgentState,
    *,
    parser: TaskParser,
) -> dict[str, object]:
    user_message = state.get('user_message', '')
    feedback = state.get('regeneration_feedback')
    if feedback:
        user_message = f'{user_message}\nRegeneration feedback: {feedback}'
    try:
        parsed = dict(
            await parser.parse(
                user_message,
                timezone=state.get('timezone', 'UTC'),
            )
        )
    except Exception as exc:
        return {'error_message': f'Task parsing failed: {exc}'}
    return {
        'task_draft': parsed,
        'parsed_task': None,
        'regeneration_feedback': None,
        'error_message': None,
    }
