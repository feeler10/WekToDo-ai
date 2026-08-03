import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.graph.builder import GraphDependencies, build_task_graph
from app.intent.enums import IntentType, TimeScope
from app.intent.models import IntentResult, TaskQueryIntent
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest
from app.schemas.task import Task, TaskStatus
from app.services.agent import TaskAgentService
from app.storage.redis_checkpoint import create_redis_checkpointer


REDIS_URL = os.getenv(
    'TEST_CHECKPOINT_REDIS_URL',
    'redis://[::1]:6379/0',
)
NOW = datetime(2026, 8, 3, 4, tzinfo=timezone.utc)
OPEN = {TaskStatus.TODO, TaskStatus.DOING, TaskStatus.BLOCKED}


class UnusedParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        raise AssertionError('parser must not run')


def _service(
    *,
    checkpointer: AsyncRedisSaver,
    repository: RedisTaskRepository,
    responses: dict[str, IntentResult],
) -> TaskAgentService:
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedParser(),
            intent_service=IntentRecognitionService(
                FakeIntentClassifier(responses=responses)
            ),
            task_repository=repository,
            clock=lambda: NOW,
        ),
        checkpointer=checkpointer,
    )
    return TaskAgentService(graph)


def _request(message: str, request_id: str) -> AgentChatRequest:
    return AgentChatRequest(
        user_id='user-1',
        thread_id='thread-1',
        request_id=request_id,
        message=message,
        timezone='Asia/Shanghai',
    )


async def _cleanup(
    redis: Redis,
    *,
    checkpoint_root: str,
) -> None:
    keys = [
        key async for key in redis.scan_iter(match=f'{checkpoint_root}:*')
    ]
    if keys:
        await redis.delete(*keys)
    for name in (
        f'{checkpoint_root}:checkpoint',
        f'{checkpoint_root}:checkpoint_write',
    ):
        try:
            await redis.execute_command('FT.DROPINDEX', name)
        except ResponseError:
            pass


@pytest.mark.integration
@pytest.mark.anyio
async def test_rebuilt_graph_restores_pending_query_clarification() -> None:
    root = f'wektodo:stage3:{uuid4().hex}'
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=f'{root}:tasks')
    incomplete = IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=1,
        reason='incomplete',
        query=TaskQueryIntent(
            time_scope=TimeScope.UNSPECIFIED,
            statuses=OPEN,
        ),
    )
    today = IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=1,
        reason='today',
        query=TaskQueryIntent(time_scope=TimeScope.TODAY),
    )
    try:
        await repository.create(
            Task(
                id='today',
                user_id='user-1',
                title='今天任务',
                deadline=datetime.fromisoformat('2026-08-03T15:00:00+08:00'),
            ),
            idempotency_key='create-today',
        )
        async with create_redis_checkpointer(
            REDIS_URL,
            key_prefix=root,
        ) as checkpointer:
            await checkpointer.asetup()
            first = _service(
                checkpointer=checkpointer,
                repository=repository,
                responses={'查看未完成任务': incomplete},
            )
            pending = await first.chat(
                _request('查看未完成任务', 'request-1')
            )
            assert pending.status == 'needs_clarification'

            rebuilt = _service(
                checkpointer=checkpointer,
                repository=repository,
                responses={'今天': today},
            )
            completed = await rebuilt.chat(_request('今天', 'request-2'))

            assert [task.id for task in completed.tasks] == ['today']
            snapshot = await rebuilt._graph.aget_state(
                rebuilt._config('user-1', 'thread-1')
            )
            assert snapshot.values.get('pending_query_clarification') is None
            assert set(snapshot.values['task_query_plan']['statuses']) == {
                'TODO',
                'DOING',
                'BLOCKED',
            }
    finally:
        await _cleanup(redis, checkpoint_root=root)
        await redis.aclose()


@pytest.mark.integration
@pytest.mark.anyio
async def test_rebuilt_graph_restores_pending_candidate_selection() -> None:
    root = f'wektodo:stage3:{uuid4().hex}'
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=f'{root}:tasks')
    query = IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=1,
        reason='specific query',
        task_reference='论文任务',
        query=TaskQueryIntent(time_scope=TimeScope.UNSPECIFIED),
    )
    fallback = IntentResult(
        intent=IntentType.UNKNOWN,
        confidence=1,
        reason='unused',
    )
    try:
        for task_id in ('task-1', 'task-2'):
            await repository.create(
                Task(
                    id=task_id,
                    user_id='user-1',
                    title='论文任务',
                ),
                idempotency_key=f'create-{task_id}',
            )
        async with create_redis_checkpointer(
            REDIS_URL,
            key_prefix=root,
        ) as checkpointer:
            await checkpointer.asetup()
            first = _service(
                checkpointer=checkpointer,
                repository=repository,
                responses={'论文任务怎么样了': query},
            )
            candidates = await first.chat(
                _request('论文任务怎么样了', 'request-1')
            )
            assert candidates.status == 'needs_disambiguation'

            rebuilt = _service(
                checkpointer=checkpointer,
                repository=repository,
                responses={'第二个': fallback},
            )
            selected = await rebuilt.chat(_request('第二个', 'request-2'))

            assert selected.task is not None
            assert selected.task.id == 'task-2'
            assert selected.pending_action is None
            snapshot = await rebuilt._graph.aget_state(
                rebuilt._config('user-1', 'thread-1')
            )
            assert snapshot.values.get('pending_task_selection') is None
    finally:
        await _cleanup(redis, checkpoint_root=root)
        await redis.aclose()
