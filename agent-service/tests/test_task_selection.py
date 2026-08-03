from datetime import datetime, timedelta, timezone

import pytest

from app.intent.enums import IntentType
from app.schemas.query_context import PendingTaskSelection
from app.schemas.task import Task, TaskStatus
from app.services.task_selection import (
    AmbiguousTaskSelectionError,
    TaskSelectionError,
    parse_candidate_selection,
)


NOW = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)


def _task(task_id: str, title: str) -> Task:
    return Task(id=task_id, user_id='user-1', title=title)


def _pending(*tasks: Task) -> PendingTaskSelection:
    return PendingTaskSelection(
        user_id='user-1',
        thread_id='thread-1',
        operation=IntentType.QUERY_TASKS,
        candidate_task_ids=[task.id for task in tasks],
        candidate_versions={task.id: task.version for task in tasks},
        reference='论文',
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ('第一个', 'task-1'),
        ('第二个', 'task-2'),
        ('1', 'task-1'),
        ('2', 'task-2'),
        ('task-2', 'task-2'),
        ('论文修改', 'task-2'),
        (' 论文 修改 ', 'task-2'),
    ],
)
def test_parse_candidate_selection_supported_forms(
    message: str,
    expected: str,
) -> None:
    tasks = [_task('task-1', '论文实验'), _task('task-2', '论文修改')]
    selected = parse_candidate_selection(
        message=message,
        pending=_pending(*tasks),
        tasks_by_id={task.id: task for task in tasks},
    )

    assert selected == expected


def test_selection_cannot_escape_candidate_set() -> None:
    tasks = [_task('task-1', '论文实验')]

    with pytest.raises(TaskSelectionError):
        parse_candidate_selection(
            message='foreign-task',
            pending=_pending(*tasks),
            tasks_by_id={
                task.id: task for task in tasks
            }
            | {'foreign-task': _task('foreign-task', '其他任务')},
        )


def test_invalid_ordinal_fails_without_selecting() -> None:
    task = _task('task-1', '论文实验')

    with pytest.raises(TaskSelectionError, match='序号'):
        parse_candidate_selection(
            message='第二个',
            pending=_pending(task),
            tasks_by_id={task.id: task},
        )


def test_duplicate_exact_titles_remain_ambiguous() -> None:
    tasks = [_task('task-1', '论文'), _task('task-2', '论文')]

    with pytest.raises(AmbiguousTaskSelectionError):
        parse_candidate_selection(
            message='论文',
            pending=_pending(*tasks),
            tasks_by_id={task.id: task for task in tasks},
        )


def test_update_selection_requires_target_status() -> None:
    task = _task('task-1', '论文')

    with pytest.raises(ValueError, match='target_status'):
        PendingTaskSelection(
            user_id='user-1',
            thread_id='thread-1',
            operation=IntentType.UPDATE_TASK_STATUS,
            candidate_task_ids=[task.id],
            candidate_versions={task.id: 1},
            reference='论文',
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
        )


def test_update_selection_accepts_minimal_operation_context() -> None:
    task = _task('task-1', '论文')

    pending = PendingTaskSelection(
        user_id='user-1',
        thread_id='thread-1',
        operation=IntentType.UPDATE_TASK_STATUS,
        candidate_task_ids=[task.id],
        candidate_versions={task.id: 1},
        reference='论文',
        target_status=TaskStatus.DOING,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )

    assert pending.target_status == TaskStatus.DOING
