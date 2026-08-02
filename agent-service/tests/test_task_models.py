from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.audit import PendingAction, ToolExecutionLog
from app.schemas.task import (
    Task,
    TaskCreate,
    TaskPriority,
    TaskQuery,
    TaskUpdate,
)


def test_task_create_accepts_timezone_aware_deadline() -> None:
    deadline = datetime(2026, 8, 7, 23, 59, tzinfo=timezone.utc)

    task = TaskCreate(user_id='user-1', title='Write tests', deadline=deadline)

    assert task.deadline == deadline


def test_task_create_rejects_naive_deadline() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(
            user_id='user-1',
            title='Write tests',
            deadline=datetime(2026, 8, 7, 23, 59),
        )


def test_task_rejects_naive_created_at() -> None:
    with pytest.raises(ValidationError):
        Task(
            id='task-1',
            user_id='user-1',
            title='Write tests',
            created_at=datetime(2026, 8, 1, 12, 0),
        )


def test_pending_action_requires_aware_ordered_timestamps() -> None:
    created_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

    action = PendingAction(
        id='action-1',
        user_id='user-1',
        thread_id='thread-1',
        action_type='create_task',
        payload={},
        idempotency_key='create_task:request-1',
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=10),
    )

    assert action.expires_at > action.created_at

    with pytest.raises(ValidationError, match='later than created_at'):
        PendingAction(
            id='action-1',
            user_id='user-1',
            thread_id='thread-1',
            action_type='create_task',
            payload={},
            idempotency_key='create_task:request-1',
            created_at=created_at,
            expires_at=created_at,
        )


def test_pending_action_rejects_naive_expiry() -> None:
    with pytest.raises(ValidationError):
        PendingAction(
            id='action-1',
            user_id='user-1',
            thread_id='thread-1',
            action_type='create_task',
            payload={},
            idempotency_key='create_task:request-1',
            expires_at=datetime(2026, 8, 1, 12, 10),
        )


def test_tool_log_rejects_naive_created_at() -> None:
    with pytest.raises(ValidationError):
        ToolExecutionLog(
            id='log-1',
            user_id='user-1',
            thread_id='thread-1',
            trace_id='trace-1',
            tool_call_id='call-1',
            tool_name='create_task',
            input_payload={},
            confirmed=True,
            success=True,
            duration_ms=10,
            created_at=datetime(2026, 8, 1, 12, 0),
        )


def test_ai_priority_is_effective_without_user_override() -> None:
    task = Task(
        id='task-1',
        user_id='user-1',
        title='Write tests',
        ai_priority=TaskPriority.HIGH,
    )

    assert task.effective_priority == TaskPriority.HIGH
    assert task.priority_source == 'ai'


def test_user_priority_overrides_ai_priority() -> None:
    task = Task(
        id='task-1',
        user_id='user-1',
        title='Write tests',
        ai_priority=TaskPriority.HIGH,
        user_priority=TaskPriority.URGENT,
    )

    assert task.effective_priority == TaskPriority.URGENT
    assert task.priority_source == 'user'


def test_task_rejects_inconsistent_effective_priority() -> None:
    with pytest.raises(ValidationError, match='effective_priority'):
        Task(
            id='task-1',
            user_id='user-1',
            title='Write tests',
            ai_priority=TaskPriority.HIGH,
            effective_priority=TaskPriority.LOW,
        )


def test_task_update_requires_at_least_one_change() -> None:
    with pytest.raises(ValidationError, match='At least one task field'):
        TaskUpdate(user_id='user-1', expected_version=1)


def test_task_query_rejects_reversed_deadline_range() -> None:
    start = datetime(2026, 8, 2, tzinfo=timezone.utc)
    end = datetime(2026, 8, 1, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match='deadline_to'):
        TaskQuery(
            user_id='user-1',
            deadline_from=start,
            deadline_to=end,
        )


def test_task_query_rejects_empty_half_open_deadline_range() -> None:
    boundary = datetime(2026, 8, 2, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match='deadline_to'):
        TaskQuery(
            user_id='user-1',
            deadline_from=boundary,
            deadline_to=boundary,
        )
