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
from app.intent.enums import IntentType
from app.intent.models import IntentResult
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest
from app.schemas.task import TaskQuery
from app.services.agent import TaskAgentService
from app.storage.redis_checkpoint import create_redis_checkpointer


REDIS_URL = os.getenv(
    'TEST_CHECKPOINT_REDIS_URL',
    'redis://[::1]:6379/0',
)
NOW = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)


class FixedParser:
    def __init__(self, result: Mapping[str, Any]) -> None:
        self.result = result
        self.calls: list[str] = []

    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        self.calls.append(user_message)
        return self.result


def service(
    *,
    checkpointer: AsyncRedisSaver,
    repository: RedisTaskRepository,
    parser: FixedParser,
) -> TaskAgentService:
    classifier = FakeIntentClassifier(
        responses={
            '创建一个周报任务': IntentResult(
                intent=IntentType.CREATE_TASK,
                confidence=1,
                reason='create task',
            )
        }
    )
    graph = build_task_graph(
        GraphDependencies(
            parser=parser,
            intent_service=IntentRecognitionService(classifier),
            task_repository=repository,
            clock=lambda: NOW,
        ),
        checkpointer=checkpointer,
    )
    return TaskAgentService(graph)


def request(message: str, request_id: str) -> AgentChatRequest:
    return AgentChatRequest(
        user_id='user-1',
        thread_id='thread-1',
        request_id=request_id,
        message=message,
        timezone='Asia/Shanghai',
    )


async def cleanup(redis: Redis, *, checkpoint_root: str) -> None:
    keys = [key async for key in redis.scan_iter(match=f'{checkpoint_root}:*')]
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
async def test_rebuilt_graph_restores_task_draft_collection() -> None:
    root = f'wektodo:draft-clarification:{uuid4().hex}'
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=f'{root}:tasks')
    first_parser = FixedParser(
        {
            'description': '准备本周汇报',
            'missing_fields': ['title'],
            'clarification_question': '任务名称是什么？',
        }
    )
    rebuilt_parser = FixedParser(
        {
            'title': '完成本周汇报',
            'description': '准备本周汇报',
        }
    )
    try:
        async with create_redis_checkpointer(
            REDIS_URL,
            key_prefix=root,
        ) as checkpointer:
            await checkpointer.asetup()
            first = service(
                checkpointer=checkpointer,
                repository=repository,
                parser=first_parser,
            )
            clarification = await first.chat(
                request('创建一个周报任务', 'request-1')
            )

            assert clarification.status == 'needs_clarification'
            assert (
                await repository.list_tasks(TaskQuery(user_id='user-1'))
            ).items == []

            rebuilt = service(
                checkpointer=checkpointer,
                repository=repository,
                parser=rebuilt_parser,
            )
            pending = await rebuilt.chat(
                request('叫完成本周汇报', 'request-2')
            )

            assert pending.status == 'awaiting_confirmation'
            assert pending.task_draft is not None
            assert pending.task_draft.title == '完成本周汇报'
            assert '[第1轮] 创建一个周报任务' in rebuilt_parser.calls[0]
            assert '[第2轮] 叫完成本周汇报' in rebuilt_parser.calls[0]
            assert (
                await repository.list_tasks(TaskQuery(user_id='user-1'))
            ).items == []

            assert pending.pending_action is not None
            completed = await rebuilt.confirm(
                AgentConfirmRequest(
                    user_id='user-1',
                    thread_id='thread-1',
                    action_id=pending.pending_action.id,
                    action='approve',
                )
            )
            assert completed.task is not None
            assert completed.task.title == '完成本周汇报'
    finally:
        await cleanup(redis, checkpoint_root=root)
        await redis.aclose()
