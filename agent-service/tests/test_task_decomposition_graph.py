from collections.abc import Mapping
from datetime import datetime, timezone
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
from app.schemas.task import Task
from app.services.agent import TaskAgentService


class UnusedTaskParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        raise AssertionError('ordinary task parser must not be called')


class SequencePlanner:
    def __init__(self, *plans: dict[str, object]) -> None:
        self._plans = list(plans)
        self.calls: list[dict[str, object]] = []

    async def generate(self, **kwargs: object) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self._plans) - 1)
        return self._plans[index]


def _plan(prefix: str = '') -> dict[str, object]:
    return {
        'summary': f'{prefix}拆解方案',
        'items': [
            {'step_key': 'prepare', 'title': f'{prefix}准备数据', 'order': 1},
            {
                'step_key': 'run',
                'title': f'{prefix}运行实验',
                'order': 2,
                'depends_on': ['prepare'],
            },
            {
                'step_key': 'report',
                'title': f'{prefix}整理结果',
                'order': 3,
                'depends_on': ['run'],
            },
        ],
    }


async def _harness(
    key_prefix: str,
    planner: SequencePlanner,
) -> tuple[FakeRedis, RedisTaskRepository, TaskAgentService]:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=key_prefix)
    await repository.create(
        Task(
            id='parent-1',
            user_id='user-1',
            title='论文实验',
            status='DOING',
            deadline=datetime(2026, 8, 20, tzinfo=timezone.utc),
        ),
        idempotency_key='parent',
    )
    intent_service = IntentRecognitionService(
        FakeIntentClassifier(
            IntentResult(
                intent=IntentType.DECOMPOSE_TASK,
                confidence=1,
                reason='测试拆解',
                task_reference='论文实验',
            )
        )
    )
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedTaskParser(),
            intent_service=intent_service,
            task_repository=repository,
            subtask_planner=planner,
        ),
        checkpointer=InMemorySaver(),
    )
    return redis, repository, TaskAgentService(graph)


def _chat_request(thread_id: str, request_id: str) -> AgentChatRequest:
    return AgentChatRequest(
        user_id='user-1',
        thread_id=thread_id,
        request_id=request_id,
        message='把论文实验拆成具体步骤',
        timezone='Asia/Shanghai',
    )


@pytest.mark.anyio
async def test_decomposition_requires_confirmation_then_creates_batch() -> None:
    planner = SequencePlanner(_plan())
    redis, repository, service = await _harness(
        'decompose:approve',
        planner,
    )
    try:
        pending = await service.chat(_chat_request('thread-1', 'request-1'))
        assert pending.status == 'awaiting_confirmation'
        assert pending.pending_action is not None
        assert pending.pending_action.action_type == 'create_subtasks_batch'
        assert pending.subtask_plan is not None
        assert await repository.list_children(
            user_id='user-1', parent_id='parent-1'
        ) == []

        completed = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-1',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )
        assert completed.status == 'completed'
        assert len(completed.subtasks) == 3
        assert all(task.parent_id == 'parent-1' for task in completed.subtasks)
        assert completed.parent_task is not None
        assert completed.parent_task.version == 2
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_decomposition_edit_and_regenerate_require_new_confirmation() -> None:
    planner = SequencePlanner(_plan(), _plan('新版'))
    redis, repository, service = await _harness(
        'decompose:review',
        planner,
    )
    try:
        first = await service.chat(_chat_request('thread-edit', 'request-edit'))
        assert first.pending_action is not None
        edited_payload = _plan('编辑后')
        edited = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-edit',
                action_id=first.pending_action.id,
                action='edit',
                edits=edited_payload,
            )
        )
        assert edited.status == 'awaiting_confirmation'
        assert edited.pending_action is not None
        assert edited.pending_action.id != first.pending_action.id
        assert edited.subtask_plan is not None
        assert edited.subtask_plan.items[0].title == '编辑后准备数据'

        second = await service.chat(
            _chat_request('thread-regenerate', 'request-regenerate')
        )
        assert second.pending_action is not None
        regenerated = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-regenerate',
                action_id=second.pending_action.id,
                action='regenerate',
                feedback='步骤更具体',
            )
        )
        assert regenerated.status == 'awaiting_confirmation'
        assert regenerated.subtask_plan is not None
        assert regenerated.subtask_plan.items[0].title == '新版准备数据'
        assert planner.calls[-1]['feedback'] == '步骤更具体'
        assert await repository.list_children(
            user_id='user-1', parent_id='parent-1'
        ) == []
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_decomposition_candidate_selection_preserves_original_request() -> None:
    planner = SequencePlanner(_plan())
    redis, repository, service = await _harness(
        'decompose:selection',
        planner,
    )
    try:
        await repository.create(
            Task(
                id='parent-2',
                user_id='user-1',
                title='论文实验',
                status='DOING',
            ),
            idempotency_key='parent-2',
        )
        candidates = await service.chat(
            _chat_request('thread-selection', 'request-selection')
        )
        assert candidates.status == 'needs_disambiguation'
        assert len(candidates.candidates) == 2

        pending = await service.chat(
            AgentChatRequest(
                user_id='user-1',
                thread_id='thread-selection',
                request_id='request-selection-choice',
                message='1',
                timezone='Asia/Shanghai',
            )
        )
        assert pending.status == 'awaiting_confirmation'
        assert planner.calls[0]['user_message'] == '把论文实验拆成具体步骤'
    finally:
        await redis.aclose()
