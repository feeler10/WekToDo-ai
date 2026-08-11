import os
from datetime import datetime, timezone
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
from app.schemas.task import Task
from app.schemas.task_attribute_update import (
    TaskFieldChange,
    TaskFieldName,
    TaskFieldOperation,
    TaskUpdateParseResult,
)
from app.services.agent import TaskAgentService
from app.storage.redis_checkpoint import create_redis_checkpointer


REDIS_URL = os.getenv(
    'TEST_CHECKPOINT_REDIS_URL',
    'redis://[::1]:6379/0',
)
NOW = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)


class UnusedCreateParser:
    async def parse(self, user_message: str, *, timezone: str) -> object:
        raise AssertionError('create parser must not run')


class FixedUpdateParser:
    def __init__(self, result: TaskUpdateParseResult) -> None:
        self.result = result
        self.calls: list[str] = []

    async def parse(
        self,
        user_message: str,
        *,
        current_task: Task,
        timezone: str,
        current_datetime: datetime,
    ) -> dict[str, object]:
        self.calls.append(user_message)
        return self.result.model_dump(mode='json')


def service(
    *,
    checkpointer: AsyncRedisSaver,
    repository: RedisTaskRepository,
    parser: FixedUpdateParser,
) -> TaskAgentService:
    intent = IntentResult(
        intent=IntentType.UPDATE_TASK,
        confidence=1,
        reason='update task',
        task_reference='接水任务',
    )
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedCreateParser(),
            task_update_parser=parser,
            intent_service=IntentRecognitionService(
                FakeIntentClassifier(result=intent)
            ),
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
async def test_rebuilt_graph_restores_task_update_collection() -> None:
    root = f'wektodo:update-clarification:{uuid4().hex}'
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=f'{root}:tasks')
    first_parser = FixedUpdateParser(
        TaskUpdateParseResult(
            changes=[],
            needs_clarification=True,
            clarification_question='你想把标题改成什么？',
            reason='缺少新标题',
        )
    )
    rebuilt_parser = FixedUpdateParser(
        TaskUpdateParseResult(
            changes=[
                TaskFieldChange(
                    field=TaskFieldName.TITLE,
                    operation=TaskFieldOperation.SET,
                    value='每天早上接水',
                )
            ],
            reason='修改标题',
        )
    )
    try:
        await repository.create(
            Task(id='water', user_id='user-1', title='接水任务'),
            idempotency_key='seed-water',
        )
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
                request('修改接水任务的标题', 'request-1')
            )

            assert clarification.status == 'needs_clarification'
            stored = await repository.get(
                user_id='user-1',
                task_id='water',
            )
            assert stored is not None and stored.version == 1

            rebuilt = service(
                checkpointer=checkpointer,
                repository=repository,
                parser=rebuilt_parser,
            )
            pending = await rebuilt.chat(
                request('改成每天早上接水', 'request-2')
            )

            assert pending.status == 'awaiting_confirmation'
            assert pending.pending_action is not None
            assert '[第1轮] 修改接水任务的标题' in rebuilt_parser.calls[0]
            assert '[第2轮] 改成每天早上接水' in rebuilt_parser.calls[0]
            stored = await repository.get(
                user_id='user-1',
                task_id='water',
            )
            assert stored is not None
            assert stored.title == '接水任务'
            assert stored.version == 1

            completed = await rebuilt.confirm(
                AgentConfirmRequest(
                    user_id='user-1',
                    thread_id='thread-1',
                    action_id=pending.pending_action.id,
                    action='approve',
                )
            )
            assert completed.task is not None
            assert completed.task.title == '每天早上接水'
            assert completed.task.version == 2
    finally:
        await cleanup(redis, checkpoint_root=root)
        await redis.aclose()
