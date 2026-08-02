import os
from uuid import uuid4

import pytest
from langgraph.types import Command
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.graph.builder import GraphDependencies, build_task_graph
from tests.intent_helpers import existing_flow_intent_service
from app.repositories.redis_task import RedisTaskRepository
from app.storage.redis_checkpoint import create_redis_checkpointer
from tests.test_human_in_the_loop import SequenceParser, _action_id, _draft, _state

REDIS_URL = os.getenv(
    'TEST_CHECKPOINT_REDIS_URL',
    'redis://127.0.0.1:6379/0',
)


@pytest.mark.integration
@pytest.mark.anyio
async def test_interrupt_resumes_from_redis_checkpoint_with_rebuilt_graph() -> None:
    unique = uuid4().hex
    checkpoint_root = f'wektodo:test:{unique}'
    task_prefix = f'{checkpoint_root}:tasks'
    checkpoint_index = f'{checkpoint_root}:checkpoint'
    write_index = f'{checkpoint_root}:checkpoint_write'
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=task_prefix)
    config = {'configurable': {'thread_id': f'redis-thread-{unique}'}}

    try:
        async with create_redis_checkpointer(
            REDIS_URL,
            key_prefix=checkpoint_root,
        ) as checkpointer:
            await checkpointer.asetup()
            first_graph = build_task_graph(
                GraphDependencies(
                    intent_service=existing_flow_intent_service(),
                    parser=SequenceParser(_draft('Redis 恢复任务')),
                    task_repository=repository,
                ),
                checkpointer=checkpointer,
            )
            interrupted = await first_graph.ainvoke(
                _state(f'redis-{unique}'),
                config=config,
            )

            rebuilt_graph = build_task_graph(
                GraphDependencies(
                    intent_service=existing_flow_intent_service(),
                    parser=SequenceParser(),
                    task_repository=repository,
                ),
                checkpointer=checkpointer,
            )
            completed = await rebuilt_graph.ainvoke(
                Command(
                    resume={
                        'action_id': _action_id(interrupted),
                        'action': 'approve',
                    }
                ),
                config=config,
            )

            assert completed['created_task']['title'] == 'Redis 恢复任务'
            stored = await repository.get(
                user_id='user-1',
                task_id=completed['created_task']['id'],
            )
            assert stored is not None
            assert stored.title == 'Redis 恢复任务'
    finally:
        keys = [
            key
            async for key in redis.scan_iter(match=f'{checkpoint_root}:*')
        ]
        if keys:
            await redis.delete(*keys)
        for index_name in (checkpoint_index, write_index):
            try:
                await redis.execute_command('FT.DROPINDEX', index_name)
            except ResponseError:
                pass
        await redis.aclose()
