from collections.abc import Mapping
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.builder import GraphDependencies, build_task_graph
from app.intent.enums import IntentType
from app.intent.models import IntentResult
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest
from app.schemas.task import Task, TaskStatus
from app.services.agent import TaskAgentService


class UnusedTaskParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        raise AssertionError('ordinary task parser must not be called')


async def _harness(
    key_prefix: str,
) -> tuple[FakeRedis, RedisTaskRepository, TaskAgentService]:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=key_prefix)
    intent_service = IntentRecognitionService(
        FakeIntentClassifier(
            IntentResult(
                intent=IntentType.DELETE_TASK,
                confidence=1,
                reason='测试删除',
                task_reference='论文实验',
            )
        )
    )
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedTaskParser(),
            intent_service=intent_service,
            task_repository=repository,
        ),
        checkpointer=InMemorySaver(),
    )
    return redis, repository, TaskAgentService(graph)


def _request(
    thread_id: str,
    request_id: str,
    message: str = '删除论文实验',
) -> AgentChatRequest:
    return AgentChatRequest(
        user_id='user-1',
        thread_id=thread_id,
        request_id=request_id,
        message=message,
        timezone='Asia/Shanghai',
    )


@pytest.mark.anyio
async def test_delete_requires_confirmation_then_removes_task() -> None:
    redis, repository, service = await _harness('delete:graph:approve')
    try:
        await repository.create(
            Task(id='task-1', user_id='user-1', title='论文实验'),
            idempotency_key='create',
        )
        pending = await service.chat(_request('thread-1', 'request-1'))

        assert pending.status == 'awaiting_confirmation'
        assert pending.pending_action is not None
        assert pending.pending_action.action_type == 'delete_task'
        assert '永久删除且不可恢复' in pending.message
        assert await repository.get(user_id='user-1', task_id='task-1')

        completed = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-1',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )
        assert completed.status == 'completed'
        assert completed.deleted_task_id == 'task-1'
        assert completed.task is None
        assert '已永久删除' in completed.message
        assert await repository.get(user_id='user-1', task_id='task-1') is None

        replay = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-1',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )
        assert replay.deleted_task_id == 'task-1'
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_rejection_keeps_task() -> None:
    redis, repository, service = await _harness('delete:graph:reject')
    try:
        await repository.create(
            Task(id='task-1', user_id='user-1', title='论文实验'),
            idempotency_key='create',
        )
        pending = await service.chat(_request('thread-2', 'request-2'))
        assert pending.pending_action is not None
        rejected = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-2',
                action_id=pending.pending_action.id,
                action='reject',
            )
        )
        assert rejected.status == 'rejected'
        assert rejected.message == '已取消删除任务。'
        assert await repository.get(user_id='user-1', task_id='task-1')
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_candidate_selection_continues_to_confirmation() -> None:
    redis, repository, service = await _harness('delete:graph:selection')
    try:
        for task_id in ('task-1', 'task-2'):
            await repository.create(
                Task(id=task_id, user_id='user-1', title='论文实验'),
                idempotency_key=f'create:{task_id}',
            )
        candidates = await service.chat(_request('thread-3', 'request-3'))
        assert candidates.status == 'needs_disambiguation'
        assert len(candidates.candidates) == 2
        assert '删除' in candidates.message

        pending = await service.chat(
            _request('thread-3', 'request-3-choice', message='1')
        )
        assert pending.status == 'awaiting_confirmation'
        assert pending.pending_action is not None
        assert pending.pending_action.action_type == 'delete_task'
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_fails_closed_when_version_changes_during_confirmation() -> None:
    redis, repository, service = await _harness('delete:graph:stale')
    try:
        await repository.create(
            Task(id='task-1', user_id='user-1', title='论文实验'),
            idempotency_key='create',
        )
        pending = await service.chat(_request('thread-4', 'request-4'))
        assert pending.pending_action is not None
        await repository.update_status(
            user_id='user-1',
            task_id='task-1',
            target_status=TaskStatus.DOING,
            expected_version=1,
            idempotency_key='concurrent-update',
        )

        failed = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-4',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )
        assert failed.status == 'error'
        assert '任务已发生变化' in failed.message
        assert await repository.get(user_id='user-1', task_id='task-1')
    finally:
        await redis.aclose()
