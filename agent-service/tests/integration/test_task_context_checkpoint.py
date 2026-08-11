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
from app.intent.enums import ClarificationReason, IntentType, TimeScope
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
NOW = datetime(2026, 8, 11, 2, tzinfo=timezone.utc)


class UnusedParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        raise AssertionError('task parser must not run')


def _service(
    *,
    checkpointer: AsyncRedisSaver,
    repository: RedisTaskRepository,
    responses: dict[str, IntentResult],
) -> TaskAgentService:
    return TaskAgentService(
        build_task_graph(
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
    )


def _request(message: str, request_id: str) -> AgentChatRequest:
    return AgentChatRequest(
        user_id='user-1',
        thread_id='thread-1',
        request_id=request_id,
        message=message,
        timezone='Asia/Shanghai',
    )


async def _cleanup(redis: Redis, root: str) -> None:
    keys = [key async for key in redis.scan_iter(match=f'{root}:*')]
    if keys:
        await redis.delete(*keys)
    for name in (f'{root}:checkpoint', f'{root}:checkpoint_write'):
        try:
            await redis.execute_command('FT.DROPINDEX', name)
        except ResponseError:
            pass


@pytest.mark.integration
@pytest.mark.anyio
async def test_rebuilt_graph_restores_active_task_context() -> None:
    root = f'wektodo:task-context:{uuid4().hex}'
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=f'{root}:tasks')
    explicit_query = IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=1,
        reason='唯一任务查询',
        task_reference='论文任务',
        query=TaskQueryIntent(time_scope=TimeScope.UNSPECIFIED),
    )
    contextual_update = IntentResult(
        intent=IntentType.UPDATE_TASK_STATUS,
        confidence=1,
        reason='上下文状态更新',
        target_status=TaskStatus.DONE,
        needs_clarification=True,
        clarification_reason=ClarificationReason.MISSING_TASK_REFERENCE,
        clarification_question='你想标记完成的是哪个任务？',
    )
    try:
        await repository.create(
            Task(
                id='paper',
                user_id='user-1',
                title='论文任务',
                status=TaskStatus.DOING,
            ),
            idempotency_key='seed-paper',
        )
        async with create_redis_checkpointer(
            REDIS_URL,
            key_prefix=root,
        ) as checkpointer:
            await checkpointer.asetup()
            first = _service(
                checkpointer=checkpointer,
                repository=repository,
                responses={'查看论文任务': explicit_query},
            )
            queried = await first.chat(_request('查看论文任务', 'request-1'))
            assert queried.task is not None and queried.task.id == 'paper'

            rebuilt = _service(
                checkpointer=checkpointer,
                repository=repository,
                responses={'把它标记完成': contextual_update},
            )
            pending = await rebuilt.chat(
                _request('把它标记完成', 'request-2')
            )

            assert pending.status == 'awaiting_confirmation'
            assert pending.pending_action is not None
            assert pending.pending_action.target_id == 'paper'
            snapshot = await rebuilt._graph.aget_state(
                rebuilt._config('user-1', 'thread-1')
            )
            assert snapshot.values['active_task_context']['task_id'] == 'paper'
    finally:
        await _cleanup(redis, root)
        await redis.aclose()
