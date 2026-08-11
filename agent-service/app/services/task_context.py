from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from app.intent.enums import IntentType
from app.schemas.task_context import ActiveTaskContext


_CONTEXT_INTENTS = {
    IntentType.QUERY_TASKS,
    IntentType.UPDATE_TASK_STATUS,
    IntentType.UPDATE_TASK,
    IntentType.DECOMPOSE_TASK,
}


def supports_active_task_context(intent: str | None) -> bool:
    try:
        return IntentType(intent) in _CONTEXT_INTENTS
    except (TypeError, ValueError):
        return False


def restore_active_task_context(
    value: object,
    *,
    user_id: str,
    thread_id: str,
    now: datetime,
) -> ActiveTaskContext | None:
    """Validate ownership and expiry of context restored from Checkpoint."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone-aware')
    if value is None:
        return None
    try:
        context = ActiveTaskContext.model_validate(value)
    except ValidationError:
        return None
    if context.user_id != user_id or context.thread_id != thread_id:
        return None
    if context.expires_at <= now:
        return None
    return context


def build_active_task_context(
    *,
    user_id: str,
    thread_id: str,
    task_id: str,
    now: datetime,
    ttl: timedelta,
) -> ActiveTaskContext:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone-aware')
    if ttl.total_seconds() <= 0:
        raise ValueError('ttl must be positive')
    return ActiveTaskContext(
        user_id=user_id,
        thread_id=thread_id,
        task_id=task_id,
        updated_at=now,
        expires_at=now + ttl,
    )


def next_active_task_id(
    state: Mapping[str, Any],
    *,
    current_task_id: str | None,
) -> str | None:
    """Select the next focus from deterministic turn outputs."""

    deleted_ids = set(state.get('deleted_task_ids') or [])
    deleted_id = state.get('deleted_task_id')
    if deleted_id:
        deleted_ids.add(str(deleted_id))
    if deleted_ids:
        return None

    for field in ('created_task', 'updated_task', 'selected_task'):
        task = state.get(field) or {}
        task_id = task.get('id') if isinstance(task, Mapping) else None
        if task_id:
            return str(task_id)

    task_results = state.get('task_results') or []
    if state.get('intent') == IntentType.QUERY_TASKS.value:
        if len(task_results) == 1:
            task = task_results[0]
            if isinstance(task, Mapping) and task.get('id'):
                return str(task['id'])
        return None

    if state.get('intent') == IntentType.CREATE_TASK.value:
        return None

    if supports_active_task_context(state.get('intent')):
        return None

    return current_task_id
