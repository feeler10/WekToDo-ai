from datetime import datetime, timedelta, timezone

import pytest
from fakeredis.aioredis import FakeRedis

from app.repositories.redis_task import RedisTaskRepository
from app.schemas.task import Task, TaskPriority, TaskQuery, TaskStatus


START = datetime(2026, 8, 2, tzinfo=timezone.utc)
END = datetime(2026, 8, 5, tzinfo=timezone.utc)


def _task(
    task_id: str,
    *,
    user_id: str = 'user-1',
    deadline: datetime | None,
    status: TaskStatus = TaskStatus.TODO,
    priority: TaskPriority = TaskPriority.MEDIUM,
) -> Task:
    return Task(
        id=task_id,
        user_id=user_id,
        title=task_id,
        deadline=deadline,
        status=status,
        ai_priority=priority,
        created_at=START,
        updated_at=START,
    )


async def _store(
    repository: RedisTaskRepository,
    *tasks: Task,
) -> None:
    for task in tasks:
        await repository.create(
            task,
            idempotency_key=f'create-{task.user_id}-{task.id}',
        )


@pytest.mark.anyio
async def test_repository_combines_user_time_status_and_priority_filters() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='stage2:combined')
    try:
        await _store(
            repository,
            _task(
                'included-at-start',
                deadline=START,
                status=TaskStatus.DOING,
                priority=TaskPriority.HIGH,
            ),
            _task(
                'excluded-at-end',
                deadline=END,
                status=TaskStatus.DOING,
                priority=TaskPriority.HIGH,
            ),
            _task(
                'excluded-before',
                deadline=START - timedelta(seconds=1),
                status=TaskStatus.DOING,
                priority=TaskPriority.HIGH,
            ),
            _task(
                'excluded-status',
                deadline=START + timedelta(days=1),
                status=TaskStatus.TODO,
                priority=TaskPriority.HIGH,
            ),
            _task(
                'excluded-priority',
                deadline=START + timedelta(days=1),
                status=TaskStatus.DOING,
                priority=TaskPriority.LOW,
            ),
            _task(
                'foreign',
                user_id='user-2',
                deadline=START + timedelta(days=1),
                status=TaskStatus.DOING,
                priority=TaskPriority.HIGH,
            ),
        )
        time_and_status = await repository.list_tasks(
            TaskQuery(
                user_id='user-1',
                deadline_from=START,
                deadline_to=END,
                statuses={TaskStatus.DOING},
            )
        )
        time_and_priority = await repository.list_tasks(
            TaskQuery(
                user_id='user-1',
                deadline_from=START,
                deadline_to=END,
                priorities={TaskPriority.HIGH},
            )
        )


        result = await repository.list_tasks(
            TaskQuery(
                user_id='user-1',
                deadline_from=START,
                deadline_to=END,
                statuses={TaskStatus.DOING},
                priorities={TaskPriority.HIGH},
            )
        )

        assert [task.id for task in result.items] == ['included-at-start']
        assert {task.id for task in time_and_status.items} == {
            'included-at-start',
            'excluded-priority',
        }
        assert {task.id for task in time_and_priority.items} == {
            'included-at-start',
            'excluded-status',
        }
        assert all(task.user_id == 'user-1' for task in result.items)
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_overdue_is_strict_and_excludes_terminal_statuses() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='stage2:overdue')
    now = END
    try:
        await _store(
            repository,
            _task(
                'open-overdue',
                deadline=now - timedelta(seconds=1),
                status=TaskStatus.DOING,
            ),
            _task(
                'exact-now',
                deadline=now,
                status=TaskStatus.DOING,
            ),
            _task(
                'done-overdue',
                deadline=now - timedelta(days=1),
                status=TaskStatus.DONE,
            ),
            _task(
                'cancelled-overdue',
                deadline=now - timedelta(days=1),
                status=TaskStatus.CANCELLED,
            ),
            _task(
                'todo-overdue',
                deadline=now - timedelta(days=1),
                status=TaskStatus.TODO,
            ),
        )

        all_open = await repository.list_tasks(
            TaskQuery(user_id='user-1', overdue_before=now)
        )
        doing_only = await repository.list_tasks(
            TaskQuery(
                user_id='user-1',
                overdue_before=now,
                statuses={TaskStatus.DOING},
            )
        )

        assert {task.id for task in all_open.items} == {
            'open-overdue',
            'todo-overdue',
        }
        assert [task.id for task in doing_only.items] == ['open-overdue']
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_redis_preserves_aware_iso_offset_and_compares_absolute_time() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='stage2:offset')
    china_time = datetime.fromisoformat('2026-08-02T08:00:00+08:00')
    try:
        await _store(
            repository,
            _task('offset-task', deadline=china_time),
        )

        payload = await redis.get(
            'stage2:offset:task:user-1:offset-task'
        )
        result = await repository.list_tasks(
            TaskQuery(
                user_id='user-1',
                deadline_from=datetime(
                    2026, 8, 2, tzinfo=timezone.utc
                ),
                deadline_to=datetime(
                    2026, 8, 3, tzinfo=timezone.utc
                ),
            )
        )

        assert payload is not None and '+08:00' in payload
        assert [task.id for task in result.items] == ['offset-task']
        assert result.items[0].deadline == china_time
    finally:
        await redis.aclose()
