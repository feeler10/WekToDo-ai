from datetime import datetime, timezone

import pytest
from fakeredis.aioredis import FakeRedis

from app.repositories.redis_task import RedisTaskRepository
from app.schemas.task import Task, TaskQuery, TaskStatus
from app.tools.task_tools import (
    get_overdue_tasks,
    get_task_detail,
    get_today_tasks,
    query_tasks,
    update_task_status,
)


async def _store(
    repository: RedisTaskRepository,
    task_id: str,
    *,
    user_id: str = 'user-1',
    deadline: datetime | None = None,
    status: TaskStatus = TaskStatus.TODO,
) -> Task:
    task = Task(
        id=task_id,
        user_id=user_id,
        title=task_id,
        deadline=deadline,
        status=status,
    )
    return await repository.create(task, idempotency_key=f'create-{task_id}')


@pytest.mark.anyio
async def test_read_tools_query_today_overdue_and_detail() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='tools:read')
    now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    try:
        today = await _store(
            repository,
            'today',
            deadline=datetime(2026, 8, 1, 15, tzinfo=timezone.utc),
        )
        await _store(
            repository,
            'overdue',
            deadline=datetime(2026, 7, 31, 12, tzinfo=timezone.utc),
            status=TaskStatus.DOING,
        )
        await _store(
            repository,
            'done-today',
            deadline=datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
            status=TaskStatus.DONE,
        )

        listed = await query_tasks(
            repository=repository,
            query=TaskQuery(user_id='user-1'),
        )
        today_result = await get_today_tasks(
            repository=repository,
            user_id='user-1',
            timezone_name='Asia/Shanghai',
            now=now,
        )
        overdue_result = await get_overdue_tasks(
            repository=repository,
            user_id='user-1',
            now=now,
        )
        detail = await get_task_detail(
            repository=repository,
            user_id='user-1',
            task_id=today.id,
        )

        assert listed.total == 3
        assert [task.id for task in today_result.items] == ['today']
        assert [task.id for task in overdue_result.items] == ['overdue']
        assert detail is not None and detail.id == 'today'
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_status_tool_requires_confirmation_and_is_idempotent() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='tools:update')
    try:
        task = await _store(repository, 'task-1')
        with pytest.raises(PermissionError, match='requires user confirmation'):
            await update_task_status(
                repository=repository,
                user_id=task.user_id,
                task_id=task.id,
                target_status=TaskStatus.DOING,
                expected_version=task.version,
                idempotency_key='update-1',
                confirmed=False,
            )

        updated = await update_task_status(
            repository=repository,
            user_id=task.user_id,
            task_id=task.id,
            target_status=TaskStatus.DOING,
            expected_version=task.version,
            idempotency_key='update-1',
            confirmed=True,
        )
        replayed = await update_task_status(
            repository=repository,
            user_id=task.user_id,
            task_id=task.id,
            target_status=TaskStatus.DOING,
            expected_version=task.version,
            idempotency_key='update-1',
            confirmed=True,
        )

        assert updated == replayed
        assert updated.status == TaskStatus.DOING
        assert updated.version == 2
        stored = await repository.get(user_id=task.user_id, task_id=task.id)
        assert stored is not None and stored.version == 2
    finally:
        await redis.aclose()
