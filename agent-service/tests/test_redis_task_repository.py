import asyncio
from datetime import datetime, timezone

import pytest
from fakeredis.aioredis import FakeRedis

from app.repositories.exceptions import (
    TaskNotFoundError,
    TaskVersionConflictError,
)
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.task import (
    Task,
    TaskPriority,
    TaskQuery,
    TaskStatus,
)
from app.services.task_state import InvalidTaskStatusTransition


def make_task(
    task_id: str,
    *,
    user_id: str = 'user-1',
    status: TaskStatus = TaskStatus.TODO,
    category: str | None = None,
    priority: TaskPriority | None = None,
) -> Task:
    return Task(
        id=task_id,
        user_id=user_id,
        title=f'Task {task_id}',
        status=status,
        category=category,
        ai_priority=priority,
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


@pytest.mark.anyio
async def test_create_get_and_list_task() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='unit:create')
    task = make_task('task-1')
    try:
        created = await repository.create(task, idempotency_key='request-1')
        fetched = await repository.get(user_id='user-1', task_id='task-1')
        listed = await repository.list_tasks(TaskQuery(user_id='user-1'))

        assert created == task
        assert fetched == task
        assert listed.total == 1
        assert listed.items == [task]
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_repeated_idempotency_key_returns_original_task() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='unit:idempotency')
    try:
        first = await repository.create(
            make_task('task-1'),
            idempotency_key='request-1',
        )
        replay = await repository.create(
            make_task('task-2'),
            idempotency_key='request-1',
        )
        listed = await repository.list_tasks(TaskQuery(user_id='user-1'))

        assert replay == first
        assert listed.total == 1
        assert listed.items[0].id == 'task-1'
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_concurrent_idempotent_creates_store_only_one_task() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='unit:concurrent')
    try:
        first, second = await asyncio.gather(
            repository.create(
                make_task('task-1'),
                idempotency_key='request-1',
            ),
            repository.create(
                make_task('task-2'),
                idempotency_key='request-1',
            ),
        )
        listed = await repository.list_tasks(TaskQuery(user_id='user-1'))

        assert first.id == second.id
        assert listed.total == 1
        assert listed.items[0].id == first.id
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_queries_are_isolated_by_user_id() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='unit:isolation')
    try:
        await repository.create(
            make_task('shared-id', user_id='user-1'),
            idempotency_key='request-1',
        )

        assert await repository.get(user_id='user-2', task_id='shared-id') is None
        other_user = await repository.list_tasks(TaskQuery(user_id='user-2'))
        assert other_user.total == 0
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_key_delimiters_cannot_bypass_user_isolation() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='unit:key-encoding')
    try:
        await repository.create(
            make_task('shared-id', user_id='team:one'),
            idempotency_key='request:1',
        )

        assert (
            await repository.get(user_id='team', task_id='one:shared-id') is None
        )
        assert (
            await repository.get(user_id='team:one', task_id='shared-id')
            is not None
        )
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_list_filters_status_category_and_priority() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='unit:filters')
    try:
        tasks = [
            make_task(
                'task-1',
                status=TaskStatus.DOING,
                category='paper',
                priority=TaskPriority.HIGH,
            ),
            make_task(
                'task-2',
                status=TaskStatus.TODO,
                category='paper',
                priority=TaskPriority.LOW,
            ),
            make_task(
                'task-3',
                status=TaskStatus.DOING,
                category='code',
                priority=TaskPriority.HIGH,
            ),
        ]
        for index, task in enumerate(tasks):
            await repository.create(task, idempotency_key=f'request-{index}')

        result = await repository.list_tasks(
            TaskQuery(
                user_id='user-1',
                statuses={TaskStatus.DOING},
                priorities={TaskPriority.HIGH},
                category='paper',
            )
        )

        assert result.total == 1
        assert result.items[0].id == 'task-1'
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_update_status_validates_transition_and_version() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='unit:update')
    try:
        await repository.create(
            make_task('task-1'),
            idempotency_key='request-1',
        )

        updated = await repository.update_status(
            user_id='user-1',
            task_id='task-1',
            target_status=TaskStatus.DOING,
            expected_version=1,
        )
        assert updated.status == TaskStatus.DOING
        assert updated.version == 2

        with pytest.raises(TaskVersionConflictError):
            await repository.update_status(
                user_id='user-1',
                task_id='task-1',
                target_status=TaskStatus.BLOCKED,
                expected_version=1,
            )
        with pytest.raises(InvalidTaskStatusTransition):
            await repository.update_status(
                user_id='user-1',
                task_id='task-1',
                target_status=TaskStatus.CANCELLED,
                expected_version=2,
            )
        with pytest.raises(TaskNotFoundError):
            await repository.update_status(
                user_id='user-2',
                task_id='task-1',
                target_status=TaskStatus.DOING,
                expected_version=1,
            )
    finally:
        await redis.aclose()
