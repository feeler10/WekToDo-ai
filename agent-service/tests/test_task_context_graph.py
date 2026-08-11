from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.builder import GraphDependencies, build_task_graph
from app.intent.enums import ClarificationReason, IntentType, TimeScope
from app.intent.models import IntentResult, TaskQueryIntent
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest
from app.schemas.task import Task, TaskStatus
from app.schemas.task_attribute_update import (
    TaskFieldChange,
    TaskFieldName,
    TaskFieldOperation,
    TaskUpdateParseResult,
)
from app.services.agent import TaskAgentService


NOW = datetime(2026, 8, 11, 2, tzinfo=timezone.utc)


class FixedCreateParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        return {
            'title': '新建任务',
            'semantic_importance': 50,
            'impact_score': 50,
        }


class FixedUpdateParser:
    def __init__(self) -> None:
        self.task_ids: list[str] = []

    async def parse(
        self,
        user_message: str,
        *,
        current_task: Task,
        timezone: str,
        current_datetime: datetime,
    ) -> Mapping[str, Any]:
        self.task_ids.append(current_task.id)
        return TaskUpdateParseResult(
            changes=[
                TaskFieldChange(
                    field=TaskFieldName.DEADLINE,
                    operation=TaskFieldOperation.SET,
                    value='2026-08-12T23:59:59+08:00',
                )
            ],
            reason='测试上下文属性修改',
        ).model_dump(mode='json')


class FixedPlanner:
    def __init__(self) -> None:
        self.parent_ids: list[str] = []

    async def generate(self, **kwargs: object) -> Mapping[str, Any]:
        parent = kwargs['parent']
        assert isinstance(parent, Task)
        self.parent_ids.append(parent.id)
        return {
            'summary': '上下文拆解方案',
            'items': [
                {'step_key': 'prepare', 'title': '准备材料', 'order': 1},
                {
                    'step_key': 'execute',
                    'title': '执行任务',
                    'order': 2,
                    'depends_on': ['prepare'],
                },
                {
                    'step_key': 'review',
                    'title': '检查结果',
                    'order': 3,
                    'depends_on': ['execute'],
                },
            ],
        }


def _query(reference: str | None = None) -> IntentResult:
    return IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=1,
        reason='测试查询',
        task_reference=reference,
        query=TaskQueryIntent(time_scope=TimeScope.UNSPECIFIED),
    )


def _contextual_status() -> IntentResult:
    return IntentResult(
        intent=IntentType.UPDATE_TASK_STATUS,
        confidence=1,
        reason='上下文状态更新',
        target_status=TaskStatus.DONE,
        needs_clarification=True,
        clarification_reason=ClarificationReason.MISSING_TASK_REFERENCE,
        clarification_question='你想标记完成的是哪个任务？',
    )


class Harness:
    def __init__(self, key_prefix: str) -> None:
        self.now = NOW
        self.redis = FakeRedis(decode_responses=True)
        self.repository = RedisTaskRepository(self.redis, key_prefix=key_prefix)
        self.update_parser = FixedUpdateParser()
        self.planner = FixedPlanner()
        responses = {
            '创建新任务': IntentResult(
                intent=IntentType.CREATE_TASK,
                confidence=1,
                reason='创建任务',
            ),
            '查看论文任务': _query('论文任务'),
            '查看周报任务': _query('周报任务'),
            '它怎么样了': _query('它'),
            '把它标记完成': _contextual_status(),
            '把这个任务截止时间改到明天': IntentResult(
                intent=IntentType.UPDATE_TASK,
                confidence=1,
                reason='上下文属性修改',
                needs_clarification=True,
                clarification_reason=ClarificationReason.MISSING_TASK_REFERENCE,
                clarification_question='你想修改哪个任务？',
            ),
            '继续拆解这个任务': IntentResult(
                intent=IntentType.DECOMPOSE_TASK,
                confidence=1,
                reason='上下文拆解',
                task_reference='这个任务',
            ),
            '查看所有任务': IntentResult(
                intent=IntentType.QUERY_TASKS,
                confidence=1,
                reason='列表查询',
                query=TaskQueryIntent(time_scope=TimeScope.ALL),
            ),
        }
        graph = build_task_graph(
            GraphDependencies(
                parser=FixedCreateParser(),
                task_update_parser=self.update_parser,
                subtask_planner=self.planner,
                intent_service=IntentRecognitionService(
                    FakeIntentClassifier(responses=responses)
                ),
                task_repository=self.repository,
                clock=lambda: self.now,
                active_task_context_ttl_seconds=60,
            ),
            checkpointer=InMemorySaver(),
        )
        self.service = TaskAgentService(graph)
        self.request_number = 0

    async def seed(self) -> None:
        for task in (
            Task(
                id='paper',
                user_id='user-1',
                title='论文任务',
                status=TaskStatus.DOING,
            ),
            Task(id='weekly', user_id='user-1', title='周报任务'),
        ):
            await self.repository.create(
                task,
                idempotency_key=f'seed-{task.id}',
            )

    async def chat(
        self,
        message: str,
        *,
        user_id: str = 'user-1',
        thread_id: str = 'thread-1',
    ):
        self.request_number += 1
        return await self.service.chat(
            AgentChatRequest(
                user_id=user_id,
                thread_id=thread_id,
                request_id=f'request-{self.request_number}',
                message=message,
                timezone='Asia/Shanghai',
            )
        )

    async def close(self) -> None:
        await self.redis.aclose()


@pytest.mark.anyio
async def test_confirmed_created_task_becomes_active_focus() -> None:
    harness = Harness('context:created')
    try:
        pending = await harness.chat('创建新任务')
        assert pending.pending_action is not None
        created = await harness.service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-1',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )
        contextual = await harness.chat('它怎么样了')

        assert created.task is not None
        assert contextual.task is not None
        assert contextual.task.id == created.task.id
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_unique_query_focus_supports_contextual_query_and_status_update() -> None:
    harness = Harness('context:query-status')
    try:
        await harness.seed()
        explicit = await harness.chat('查看论文任务')
        contextual = await harness.chat('它怎么样了')
        pending = await harness.chat('把它标记完成')

        assert explicit.task is not None and explicit.task.id == 'paper'
        assert contextual.task is not None and contextual.task.id == 'paper'
        assert pending.status == 'awaiting_confirmation', pending.message
        assert pending.pending_action is not None
        assert pending.pending_action.target_id == 'paper'
        before = await harness.repository.get(user_id='user-1', task_id='paper')
        assert before is not None and before.status == TaskStatus.DOING

        completed = await harness.service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-1',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )
        assert completed.task is not None
        assert completed.task.status == TaskStatus.DONE
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_contextual_attribute_update_and_decomposition_reuse_existing_flows() -> None:
    harness = Harness('context:update-decompose')
    try:
        await harness.seed()
        await harness.chat('查看论文任务')
        update = await harness.chat('把这个任务截止时间改到明天')

        assert update.status == 'awaiting_confirmation'
        assert update.pending_action is not None
        assert update.pending_action.target_id == 'paper'
        assert harness.update_parser.task_ids == ['paper']

        await harness.service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-1',
                action_id=update.pending_action.id,
                action='reject',
            )
        )
        decomposition = await harness.chat('继续拆解这个任务')

        assert decomposition.status == 'awaiting_confirmation'
        assert decomposition.pending_action is not None
        assert decomposition.pending_action.target_id == 'paper'
        assert harness.planner.parent_ids == ['paper']
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_explicit_reference_overrides_focus_and_multi_result_clears_it() -> None:
    harness = Harness('context:override-clear')
    try:
        await harness.seed()
        await harness.chat('查看论文任务')
        weekly = await harness.chat('查看周报任务')
        contextual = await harness.chat('它怎么样了')

        assert weekly.task is not None and weekly.task.id == 'weekly'
        assert contextual.task is not None and contextual.task.id == 'weekly'

        listed = await harness.chat('查看所有任务')
        unresolved = await harness.chat('把它标记完成')

        assert len(listed.tasks) == 2
        assert unresolved.status == 'needs_clarification'
        assert unresolved.pending_action is None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_context_expires_and_isolated_by_user_and_thread() -> None:
    harness = Harness('context:isolation')
    try:
        await harness.seed()
        await harness.chat('查看论文任务')

        other_thread = await harness.chat(
            '把它标记完成',
            thread_id='thread-2',
        )
        other_user = await harness.chat(
            '把它标记完成',
            user_id='user-2',
        )
        harness.now += timedelta(seconds=60)
        expired = await harness.chat('把它标记完成')

        assert other_thread.status == 'needs_clarification'
        assert other_user.status == 'needs_clarification'
        assert expired.status == 'needs_clarification'
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_deleted_focus_is_not_treated_as_task_fact() -> None:
    harness = Harness('context:deleted')
    try:
        await harness.seed()
        await harness.chat('查看论文任务')
        stored = await harness.repository.get(user_id='user-1', task_id='paper')
        assert stored is not None
        await harness.repository.delete(
            user_id='user-1',
            task_id='paper',
            expected_version=stored.version,
            idempotency_key='delete-focused-paper',
        )

        response = await harness.chat('把它标记完成')
        snapshot = await harness.service._graph.aget_state(
            harness.service._config('user-1', 'thread-1')
        )

        assert response.pending_action is None
        assert response.status == 'completed'
        assert snapshot.values.get('active_task_context') is None
    finally:
        await harness.close()
