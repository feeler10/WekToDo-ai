from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from app.graph.state import TaskAgentState
from app.graph.task_update_parser import TaskUpdateParser
from app.schemas.task import Task
from app.schemas.task_attribute_update import TaskUpdateParseResult
from app.services.task_attribute_update import build_task_update


async def parse_task_update(
    state: TaskAgentState,
    *,
    parser: TaskUpdateParser | None,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    if parser is None:
        return {'error_message': 'Task update parser is not configured'}
    try:
        task = Task.model_validate(state.get('selected_task'))
        timezone_name = state.get('timezone', 'UTC')
        current_datetime = clock()
        if (
            current_datetime.tzinfo is None
            or current_datetime.utcoffset() is None
        ):
            raise ValueError('clock must return a timezone-aware datetime')
        parsed = TaskUpdateParseResult.model_validate(
            await parser.parse(
                state.get('task_update_message')
                or state.get('user_message', ''),
                current_task=task,
                timezone=timezone_name,
                current_datetime=current_datetime.astimezone(
                    ZoneInfo(timezone_name)
                ),
            )
        )
        if parsed.needs_clarification:
            return {
                'task_update_result': parsed.model_dump(mode='json'),
                'task_update': None,
                'final_response': parsed.clarification_question,
                'error_message': None,
            }
        update = build_task_update(
            parsed,
            user_id=task.user_id,
            expected_version=task.version,
        )
    except Exception as exc:
        return {'error_message': f'Task update parsing failed: {exc}'}
    return {
        'task_update_result': parsed.model_dump(mode='json'),
        'task_update': update.model_dump(mode='json', exclude_unset=True),
        'final_response': None,
        'error_message': None,
    }
