import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from langgraph.types import Command
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.graph.builder import GraphDependencies, build_task_graph
from app.intent.enums import IntentType
from app.intent.models import IntentResult
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from tests.intent_helpers import existing_flow_intent_service
from app.repositories.redis_task import RedisTaskRepository
from app.storage.redis_checkpoint import create_redis_checkpointer
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest
from app.schemas.task import Task, TaskStatus
from app.schemas.task_deletion import TaskDeleteParseResult
from app.services.agent import TaskAgentService
from tests.test_human_in_the_loop import SequenceParser, _action_id, _draft, _state

REDIS_URL = os.getenv(
    'TEST_CHECKPOINT_REDIS_URL',
    'redis://[::1]:6379/0',
)
TASK_REDIS_URL = os.getenv('TEST_REDIS_URL', 'redis://[::1]:6379/15')


class FixedDeleteSelectionParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
        current_datetime: datetime,
    ) -> Mapping[str, Any]:
        return TaskDeleteParseResult.model_validate(
            {
                'query': {'time_scope': 'ALL'},
                'task_references': ['同名删除目标', '唯一删除目标'],
                'delete_all_matches': True,
                'reason': 'IPv6 Checkpoint 删除逐项消歧',
            }
        ).model_dump(mode='json')


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


@pytest.mark.integration
@pytest.mark.anyio
async def test_delete_interrupt_resumes_from_ipv6_redis_checkpoint() -> None:
    unique = uuid4().hex
    checkpoint_root = f'wektodo:test:delete:{unique}'
    task_prefix = f'{checkpoint_root}:tasks'
    checkpoint_index = f'{checkpoint_root}:checkpoint'
    write_index = f'{checkpoint_root}:checkpoint_write'
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=task_prefix)
    config = {'configurable': {'thread_id': f'delete-thread-{unique}'}}
    intent_service = IntentRecognitionService(
        FakeIntentClassifier(
            IntentResult(
                intent=IntentType.DELETE_TASK,
                confidence=1,
                reason='集成测试删除',
                task_reference='真实删除任务',
            )
        )
    )
    initial_state = {
        'user_id': 'integration-user',
        'thread_id': f'delete-thread-{unique}',
        'user_message': '删除真实删除任务',
        'timezone': 'Asia/Shanghai',
        'request_id': f'delete-request-{unique}',
    }

    try:
        await repository.create(
            Task(
                id='delete-target',
                user_id='integration-user',
                title='真实删除任务',
            ),
            idempotency_key='create-delete-target',
        )
        async with create_redis_checkpointer(
            REDIS_URL,
            key_prefix=checkpoint_root,
        ) as checkpointer:
            await checkpointer.asetup()
            first_graph = build_task_graph(
                GraphDependencies(
                    intent_service=intent_service,
                    parser=SequenceParser(),
                    task_repository=repository,
                ),
                checkpointer=checkpointer,
            )
            interrupted = await first_graph.ainvoke(initial_state, config=config)

            rebuilt_graph = build_task_graph(
                GraphDependencies(
                    intent_service=intent_service,
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

            assert completed['deleted_task_id'] == 'delete-target'
            assert await repository.get(
                user_id='integration-user',
                task_id='delete-target',
            ) is None
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


@pytest.mark.integration
@pytest.mark.anyio
async def test_cancelled_restore_then_original_intent_resumes_from_ipv6_checkpoint() -> None:
    unique = uuid4().hex
    checkpoint_root = f'wektodo:test:restore:{unique}'
    task_prefix = f'{checkpoint_root}:tasks'
    checkpoint_index = f'{checkpoint_root}:checkpoint'
    write_index = f'{checkpoint_root}:checkpoint_write'
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=task_prefix)
    config = {'configurable': {'thread_id': f'restore-thread-{unique}'}}
    intent_service = IntentRecognitionService(
        FakeIntentClassifier(
            intent=IntentType.UPDATE_TASK_STATUS,
            task_reference='IPv6 恢复任务',
            target_status=TaskStatus.DOING,
            reason='恢复后继续原状态意图',
        )
    )
    initial_state = {
        'user_id': 'integration-user',
        'thread_id': f'restore-thread-{unique}',
        'user_message': '继续 IPv6 恢复任务',
        'timezone': 'Asia/Shanghai',
        'request_id': f'restore-request-{unique}',
    }
    try:
        await repository.create(
            Task(
                id='restore-target',
                user_id='integration-user',
                title='IPv6 恢复任务',
                status=TaskStatus.CANCELLED,
            ),
            idempotency_key='create-restore-target',
        )
        async with create_redis_checkpointer(
            REDIS_URL,
            key_prefix=checkpoint_root,
        ) as checkpointer:
            await checkpointer.asetup()
            first_graph = build_task_graph(
                GraphDependencies(
                    intent_service=intent_service,
                    parser=SequenceParser(),
                    task_repository=repository,
                ),
                checkpointer=checkpointer,
            )
            restore_pending = await first_graph.ainvoke(
                initial_state,
                config=config,
            )
            assert restore_pending['pending_action']['action_type'] == 'restore_task'

            second_graph = build_task_graph(
                GraphDependencies(
                    intent_service=intent_service,
                    parser=SequenceParser(),
                    task_repository=repository,
                ),
                checkpointer=checkpointer,
            )
            update_pending = await second_graph.ainvoke(
                Command(
                    resume={
                        'action_id': _action_id(restore_pending),
                        'action': 'approve',
                    }
                ),
                config=config,
            )
            assert update_pending['pending_action']['action_type'] == 'update_task_status'

            third_graph = build_task_graph(
                GraphDependencies(
                    intent_service=intent_service,
                    parser=SequenceParser(),
                    task_repository=repository,
                ),
                checkpointer=checkpointer,
            )
            completed = await third_graph.ainvoke(
                Command(
                    resume={
                        'action_id': _action_id(update_pending),
                        'action': 'approve',
                    }
                ),
                config=config,
            )
            assert completed['updated_task']['status'] == TaskStatus.DOING.value
            stored = await repository.get(
                user_id='integration-user',
                task_id='restore-target',
            )
            assert stored is not None
            assert stored.status == TaskStatus.DOING
            assert stored.version == 3
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


@pytest.mark.integration
@pytest.mark.anyio
async def test_batch_delete_disambiguation_resumes_from_ipv6_checkpoint() -> None:
    unique = uuid4().hex
    checkpoint_root = f'wektodo:test:delete-selection:{unique}'
    task_prefix = f'{checkpoint_root}:tasks'
    checkpoint_index = f'{checkpoint_root}:checkpoint'
    write_index = f'{checkpoint_root}:checkpoint_write'
    checkpoint_redis = Redis.from_url(REDIS_URL, decode_responses=True)
    task_redis = Redis.from_url(TASK_REDIS_URL, decode_responses=True)
    repository = RedisTaskRepository(task_redis, key_prefix=task_prefix)
    thread_id = f'delete-selection-{unique}'
    intent_service = IntentRecognitionService(
        FakeIntentClassifier(
            intent=IntentType.DELETE_TASK,
            reason='IPv6 删除逐项消歧',
        )
    )
    try:
        for task_id, title in (
            ('duplicate-1', '同名删除目标'),
            ('duplicate-2', '同名删除目标'),
            ('unique', '唯一删除目标'),
        ):
            await repository.create(
                Task(
                    id=task_id,
                    user_id='integration-user',
                    title=title,
                ),
                idempotency_key=f'create:{task_id}',
            )

        async with create_redis_checkpointer(
            REDIS_URL,
            key_prefix=checkpoint_root,
        ) as checkpointer:
            await checkpointer.asetup()
            first_service = TaskAgentService(
                build_task_graph(
                    GraphDependencies(
                        intent_service=intent_service,
                        parser=SequenceParser(),
                        task_delete_parser=FixedDeleteSelectionParser(),
                        task_repository=repository,
                    ),
                    checkpointer=checkpointer,
                )
            )
            candidates = await first_service.chat(
                AgentChatRequest(
                    user_id='integration-user',
                    thread_id=thread_id,
                    request_id=f'delete-selection-request-{unique}',
                    message='删除同名删除目标和唯一删除目标',
                    timezone='Asia/Shanghai',
                )
            )
            assert candidates.status == 'needs_disambiguation'
            assert {task.id for task in candidates.candidates} == {
                'duplicate-1',
                'duplicate-2',
            }

            rebuilt_service = TaskAgentService(
                build_task_graph(
                    GraphDependencies(
                        intent_service=intent_service,
                        parser=SequenceParser(),
                        task_delete_parser=FixedDeleteSelectionParser(),
                        task_repository=repository,
                    ),
                    checkpointer=checkpointer,
                )
            )
            pending = await rebuilt_service.chat(
                AgentChatRequest(
                    user_id='integration-user',
                    thread_id=thread_id,
                    request_id=f'delete-selection-choice-{unique}',
                    message='duplicate-2',
                    timezone='Asia/Shanghai',
                )
            )
            assert pending.pending_action is not None
            assert {task.id for task in pending.deletion_tasks} == {
                'duplicate-2',
                'unique',
            }

            completed = await rebuilt_service.confirm(
                AgentConfirmRequest(
                    user_id='integration-user',
                    thread_id=thread_id,
                    action_id=pending.pending_action.id,
                    action='approve',
                )
            )
            assert set(completed.deleted_task_ids) == {
                'duplicate-2',
                'unique',
            }
            assert await repository.get(
                user_id='integration-user', task_id='duplicate-1'
            )
    finally:
        task_keys = [
            key async for key in task_redis.scan_iter(match=f'{task_prefix}:*')
        ]
        if task_keys:
            await task_redis.delete(*task_keys)
        checkpoint_keys = [
            key
            async for key in checkpoint_redis.scan_iter(
                match=f'{checkpoint_root}:*'
            )
        ]
        if checkpoint_keys:
            await checkpoint_redis.delete(*checkpoint_keys)
        for index_name in (checkpoint_index, write_index):
            try:
                await checkpoint_redis.execute_command(
                    'FT.DROPINDEX', index_name
                )
            except ResponseError:
                pass
        await task_redis.aclose()
        await checkpoint_redis.aclose()
