from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from app.graph.state import TaskAgentState
from app.graph.task_update_parser import TaskUpdateParser
from app.schemas.task import Task
from app.schemas.task_attribute_update import TaskUpdateParseResult
from app.services.task_attribute_update import build_task_update
from app.services.task_update_clarification import (
    format_task_update_collection_input,
)
from app.services.error_mapping import error_state
from app.services.exceptions import ComponentNotConfiguredError, ModelUnavailableError


async def parse_task_update(
    state: TaskAgentState,
    *,
    parser: TaskUpdateParser | None,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    if parser is None:
        return error_state(
            ComponentNotConfiguredError(),
            trace_id=state.get('trace_id'),
        )
    try:
        task = Task.model_validate(state.get('selected_task'))
        timezone_name = state.get('timezone', 'UTC')
        task_update_inputs = list(state.get('task_update_inputs') or [])
        if not task_update_inputs:
            task_update_inputs = [
                state.get('task_update_message')
                or state.get('user_message', '')
            ]
        user_message = format_task_update_collection_input(
            task_update_inputs
        )
        current_datetime = clock()
        if (
            current_datetime.tzinfo is None
            or current_datetime.utcoffset() is None
        ):
            raise ValueError('clock must return a timezone-aware datetime')
        parsed = TaskUpdateParseResult.model_validate(
            await parser.parse(
                user_message,
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
                'task_update_inputs': task_update_inputs,
                'final_response': None,
                'error_message': None,
            }
        update = build_task_update(
            parsed,
            user_id=task.user_id,
            expected_version=task.version,
        )
    except Exception as exc:
        return error_state(
            ModelUnavailableError() if not isinstance(exc, ModelUnavailableError) else exc,
            trace_id=state.get('trace_id'),
        )
    return {
        'task_update_result': parsed.model_dump(mode='json'),
        'task_update': update.model_dump(mode='json', exclude_unset=True),
        'pending_task_update_clarification': None,
        'task_update_inputs': task_update_inputs,
        'final_response': None,
        'error_message': None,
    }
