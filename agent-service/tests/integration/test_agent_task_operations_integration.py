import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from redis.asyncio import Redis

from app.graph.builder import GraphDependencies, build_task_graph
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest
from app.schemas.task import Task, TaskStatus
from app.services.agent import TaskAgentService

REDIS_URL = os.getenv('TEST_REDIS_URL', 'redis://127.0.0.1:6379/15')


class UnusedParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        raise AssertionError('Query and update paths must not call the task parser')


@pytest.mark.integration
@pytest.mark.anyio
async def test_agent_query_and_confirmed_update_use_real_redis_data() -> None:
    unique = uuid4().hex
    key_prefix = f'wektodo:test:agent-operations:{unique}'
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=key_prefix)
    task = Task(
        id='real-task',
        user_id='integration-user',
        title='真实 Redis 任务',
    )
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedParser(),
            task_repository=repository,
            clock=lambda: datetime(2026, 8, 1, tzinfo=timezone.utc),
        ),
        checkpointer=InMemorySaver(),
    )
    service = TaskAgentService(graph)

    try:
        await repository.create(task, idempotency_key='create-real-task')
        queried = await service.chat(
            AgentChatRequest(
                user_id=task.user_id,
                thread_id='query-thread',
                request_id='query-request',
                message='查询我的任务',
                timezone='Asia/Shanghai',
            )
        )
        pending = await service.chat(
            AgentChatRequest(
                user_id=task.user_id,
                thread_id='update-thread',
                request_id='update-request',
                message='把真实 Redis 任务标记为进行中',
                timezone='Asia/Shanghai',
            )
        )
        assert pending.pending_action is not None
        updated = await service.confirm(
            AgentConfirmRequest(
                user_id=task.user_id,
                thread_id=pending.thread_id,
                action_id=pending.pending_action.id,
                action='approve',
            )
        )

        assert [item.id for item in queried.tasks] == [task.id]
        assert updated.task is not None
        assert updated.task.status == TaskStatus.DOING
        stored = await repository.get(user_id=task.user_id, task_id=task.id)
        assert stored is not None and stored.status == TaskStatus.DOING
    finally:
        keys = [key async for key in redis.scan_iter(match=f'{key_prefix}:*')]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
