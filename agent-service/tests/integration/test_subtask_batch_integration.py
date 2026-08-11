import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.repositories.redis_task import RedisTaskRepository
from app.schemas.subtask import SubtaskBatchCreate
from app.schemas.task import Task, TaskStatus


REDIS_URL = os.getenv('TEST_REDIS_URL', 'redis://[::1]:6379/15')


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_redis_batch_create_and_parent_rollup() -> None:
    key_prefix = f'wektodo:test:subtasks:{uuid4().hex}'
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=key_prefix)
    try:
        assert await redis.ping()
        await repository.create(
            Task(
                id='parent',
                user_id='integration-user',
                title='真实 Redis 父任务',
                status=TaskStatus.DOING,
            ),
            idempotency_key='parent',
        )
        batch = await repository.create_subtasks_batch(
            SubtaskBatchCreate.model_validate(
                {
                    'user_id': 'integration-user',
                    'parent_task_id': 'parent',
                    'expected_parent_version': 1,
                    'items': [
                        {'step_key': 'a', 'title': '步骤 A', 'order': 1},
                        {'step_key': 'b', 'title': '步骤 B', 'order': 2},
                        {'step_key': 'c', 'title': '步骤 C', 'order': 3},
                    ],
                }
            ),
            idempotency_key='batch',
        )
        for child in batch.subtasks:
            doing = await repository.update_status_with_rollup(
                user_id='integration-user',
                task_id=child.id,
                target_status=TaskStatus.DOING,
                expected_version=1,
                idempotency_key=f'doing:{child.id}',
            )
            await repository.update_status_with_rollup(
                user_id='integration-user',
                task_id=child.id,
                target_status=TaskStatus.DONE,
                expected_version=doing.task.version,
                idempotency_key=f'done:{child.id}',
            )

        parent = await repository.get(
            user_id='integration-user',
            task_id='parent',
        )
        assert parent is not None
        assert parent.status == TaskStatus.DONE
        assert parent.progress == 100
        assert parent.completed_at is not None

        deleted = await repository.delete(
            user_id='integration-user',
            task_id=batch.subtasks[-1].id,
            expected_version=3,
            idempotency_key='delete:last-child',
        )
        replay = await repository.delete(
            user_id='integration-user',
            task_id=batch.subtasks[-1].id,
            expected_version=3,
            idempotency_key='delete:last-child',
        )
        remaining = await repository.list_children(
            user_id='integration-user',
            parent_id='parent',
        )
        assert [task.id for task in remaining] == [
            task.id for task in batch.subtasks[:-1]
        ]
        assert deleted.parent_task is not None
        assert deleted.parent_task.status == TaskStatus.DONE
        assert deleted.parent_task.progress == 100
        assert replay.replayed is True
        assert replay.parent_task is not None
        assert replay.parent_task.version == deleted.parent_task.version
    finally:
        keys = [key async for key in redis.scan_iter(match=f'{key_prefix}:*')]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
