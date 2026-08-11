from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.intent.task_reference import is_contextual_task_reference
from app.schemas.task_context import ActiveTaskContext
from app.services.task_context import (
    build_active_task_context,
    next_active_task_id,
    restore_active_task_context,
)


NOW = datetime(2026, 8, 11, 2, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ('reference', 'message'),
    [
        ('它', '把它标记完成'),
        ('这个任务', '修改这个任务'),
        (None, '继续拆解刚才提到的任务'),
        (None, '上面这个任务完成得怎么样了'),
    ],
)
def test_recognizes_controlled_singular_task_references(
    reference: str | None,
    message: str,
) -> None:
    assert is_contextual_task_reference(reference, message) is True


@pytest.mark.parametrize(
    ('reference', 'message'),
    [
        (None, '把这个时间改到明天'),
        (None, '查看那个分类'),
        ('论文任务', '查看论文任务'),
        (None, '把这些任务标记完成'),
        (None, '把它们标记完成'),
    ],
)
def test_does_not_expand_beyond_singular_task_references(
    reference: str | None,
    message: str,
) -> None:
    assert is_contextual_task_reference(reference, message) is False


def test_active_task_context_requires_aware_ordered_timestamps() -> None:
    with pytest.raises(ValidationError):
        ActiveTaskContext(
            user_id='user-1',
            thread_id='thread-1',
            task_id='task-1',
            updated_at=NOW,
            expires_at=NOW,
        )


def test_restore_context_checks_owner_thread_and_expiry() -> None:
    context = build_active_task_context(
        user_id='user-1',
        thread_id='thread-1',
        task_id='task-1',
        now=NOW,
        ttl=timedelta(minutes=30),
    )

    assert restore_active_task_context(
        context,
        user_id='user-1',
        thread_id='thread-1',
        now=NOW,
    ) == context
    assert restore_active_task_context(
        context,
        user_id='user-2',
        thread_id='thread-1',
        now=NOW,
    ) is None
    assert restore_active_task_context(
        context,
        user_id='user-1',
        thread_id='thread-2',
        now=NOW,
    ) is None
    assert restore_active_task_context(
        context,
        user_id='user-1',
        thread_id='thread-1',
        now=NOW + timedelta(minutes=30),
    ) is None


def test_focus_policy_uses_unique_results_and_clears_ambiguous_results() -> None:
    assert next_active_task_id(
        {
            'intent': 'QUERY_TASKS',
            'task_results': [{'id': 'task-1'}],
        },
        current_task_id=None,
    ) == 'task-1'
    assert next_active_task_id(
        {
            'intent': 'QUERY_TASKS',
            'task_results': [{'id': 'task-1'}, {'id': 'task-2'}],
        },
        current_task_id='old-task',
    ) is None
    assert next_active_task_id(
        {
            'intent': 'UPDATE_TASK_STATUS',
            'selected_task': {'id': 'task-2'},
        },
        current_task_id='task-1',
    ) == 'task-2'
    assert next_active_task_id(
        {
            'intent': 'GENERAL_CHAT',
        },
        current_task_id='task-1',
    ) == 'task-1'
