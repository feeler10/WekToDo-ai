from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.builder import GraphDependencies, build_task_graph
from app.graph.routing import route_after_task_reference_resolution
from app.intent.enums import IntentType
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest
from app.schemas.task import Task, TaskStatus
from app.services.agent import TaskAgentService
from app.services.task_response import format_task_detail_response


NOW = datetime(2026, 8, 11, 2, tzinfo=timezone.utc)


class UnusedTaskParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        raise AssertionError('create parser must not be called')


async def _harness(
    key_prefix: str,
) -> tuple[FakeRedis, RedisTaskRepository, TaskAgentService]:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=key_prefix)
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedTaskParser(),
            intent_service=IntentRecognitionService(
                FakeIntentClassifier(
                    intent=IntentType.UPDATE_TASK_STATUS,
                    task_reference='论文任务',
                    target_status=TaskStatus.DOING,
                    reason='继续已取消任务',
                )
            ),
            task_repository=repository,
            clock=lambda: NOW,
        ),
        checkpointer=InMemorySaver(),
    )
    return redis, repository, TaskAgentService(graph)


def _request(thread_id: str) -> AgentChatRequest:
    return AgentChatRequest(
        user_id='user-1',
        thread_id=thread_id,
        request_id=f'request-{thread_id}',
        message='继续论文任务',
        timezone='Asia/Shanghai',
    )


@pytest.mark.anyio
async def test_cancelled_task_restores_then_continues_original_status_intent() -> None:
    redis, repository, service = await _harness('restore:continue')
    try:
        await repository.create(
            Task(
                id='paper',
                user_id='user-1',
                title='论文任务',
                status=TaskStatus.CANCELLED,
            ),
            idempotency_key='create-paper',
        )

        restore = await service.chat(_request('restore-continue'))
        assert restore.status == 'awaiting_confirmation'
        assert restore.pending_action is not None
        assert restore.pending_action.action_type == 'restore_task'
        assert restore.pending_action.payload['target_status'] == 'TODO'

        update = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='restore-continue',
                action_id=restore.pending_action.id,
                action='approve',
            )
        )
        assert update.status == 'awaiting_confirmation'
        assert update.pending_action is not None
        assert update.pending_action.action_type == 'update_task_status'
        assert update.pending_action.payload['current_status'] == 'TODO'
        assert update.pending_action.payload['target_status'] == 'DOING'

        completed = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='restore-continue',
                action_id=update.pending_action.id,
                action='approve',
            )
        )
        assert completed.task is not None
        assert completed.task.status == TaskStatus.DOING
        assert completed.task.version == 3
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_rejecting_restore_keeps_task_cancelled() -> None:
    redis, repository, service = await _harness('restore:reject')
    try:
        await repository.create(
            Task(
                id='paper',
                user_id='user-1',
                title='论文任务',
                status=TaskStatus.CANCELLED,
            ),
            idempotency_key='create-paper',
        )
        restore = await service.chat(_request('restore-reject'))
        assert restore.pending_action is not None
        rejected = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='restore-reject',
                action_id=restore.pending_action.id,
                action='reject',
            )
        )
        stored = await repository.get(user_id='user-1', task_id='paper')
        assert rejected.status == 'rejected'
        assert stored is not None and stored.status == TaskStatus.CANCELLED
    finally:
        await redis.aclose()


def test_cancelled_task_detail_explains_restore_gate() -> None:
    task = Task(
        id='paper',
        user_id='user-1',
        title='论文任务',
        status=TaskStatus.CANCELLED,
    )

    response = format_task_detail_response(
        task,
        timezone_name='Asia/Shanghai',
    )

    assert '已被取消' in response
    assert '先恢复为待办' in response


@pytest.mark.parametrize(
    ('intent', 'expected'),
    [
        (IntentType.UPDATE_TASK_STATUS, 'prepare_task_restore'),
        (IntentType.UPDATE_TASK, 'prepare_task_restore'),
        (IntentType.DECOMPOSE_TASK, 'prepare_task_restore'),
        (IntentType.DELETE_TASK, 'prepare_task_delete'),
    ],
)
def test_cancelled_restore_gate_excludes_delete(
    intent: IntentType,
    expected: str,
) -> None:
    route = route_after_task_reference_resolution(
        {
            'intent': intent.value,
            'target_status': TaskStatus.DOING.value,
            'selected_task': {
                'id': 'paper',
                'status': TaskStatus.CANCELLED.value,
            },
        }
    )

    assert route == expected
