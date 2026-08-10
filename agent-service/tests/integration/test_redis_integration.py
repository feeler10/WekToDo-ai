import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.core.config import Settings
from app.main import create_app
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.task import Task, TaskQuery, TaskStatus

REDIS_URL = os.getenv('TEST_REDIS_URL', 'redis://[::1]:6379/15')


@pytest.mark.integration
def test_redis_health_endpoint_with_real_redis() -> None:
    settings = Settings(app_env='test', redis_url=REDIS_URL)

    with TestClient(create_app(settings)) as client:
        response = client.get('/health/redis')

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


@pytest.mark.integration
@pytest.mark.anyio
async def test_redis_repository_end_to_end() -> None:
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    key_prefix = f'wektodo:test:{uuid4().hex}'
    repository = RedisTaskRepository(redis, key_prefix=key_prefix)
    task = Task(id='task-1', user_id='integration-user', title='Integration task')

    try:
        assert await redis.ping()

        created = await repository.create(task, idempotency_key='request-1')
        replayed = await repository.create(
            Task(id='task-2', user_id='integration-user', title='Duplicate'),
            idempotency_key='request-1',
        )
        fetched = await repository.get(
            user_id='integration-user',
            task_id='task-1',
        )
        listed = await repository.list_tasks(
            TaskQuery(user_id='integration-user')
        )
        updated = await repository.update_status(
            user_id='integration-user',
            task_id='task-1',
            target_status=TaskStatus.DOING,
            expected_version=1,
        )

        assert created.id == 'task-1'
        assert replayed.id == 'task-1'
        assert fetched is not None and fetched.id == 'task-1'
        assert listed.total == 1
        assert updated.status == TaskStatus.DOING
        assert updated.version == 2
    finally:
        keys = [key async for key in redis.scan_iter(match=f'{key_prefix}:*')]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
