from app.graph.parser import TaskParser
from app.graph.state import TaskAgentState
from app.services.task_draft_clarification import format_task_collection_input


async def parse_task(
    state: TaskAgentState,
    *,
    parser: TaskParser,
) -> dict[str, object]:
    task_collection_inputs = list(state.get('task_collection_inputs') or [])
    if not task_collection_inputs:
        task_collection_inputs = [state.get('user_message', '')]
    user_message = format_task_collection_input(task_collection_inputs)
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
        'task_collection_inputs': task_collection_inputs,
        'regeneration_feedback': None,
        'error_message': None,
    }
