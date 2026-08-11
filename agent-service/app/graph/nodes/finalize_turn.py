from collections.abc import Callable
from datetime import datetime, timedelta

from app.graph.state import TaskAgentState
from app.services.task_context import (
    build_active_task_context,
    next_active_task_id,
    restore_active_task_context,
)


def finalize_turn(
    state: TaskAgentState,
    *,
    clock: Callable[[], datetime],
    context_ttl: timedelta,
) -> dict[str, object]:
    now = clock()
    current = restore_active_task_context(
        state.get('active_task_context'),
        user_id=state['user_id'],
        thread_id=state['thread_id'],
        now=now,
    )
    task_id = next_active_task_id(
        state,
        current_task_id=current.task_id if current is not None else None,
    )
    if task_id is None:
        return {'active_task_context': None}
    return {
        'active_task_context': build_active_task_context(
            user_id=state['user_id'],
            thread_id=state['thread_id'],
            task_id=task_id,
            now=now,
            ttl=context_ttl,
        ).model_dump(mode='json')
    }
