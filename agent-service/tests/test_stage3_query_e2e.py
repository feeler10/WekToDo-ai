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
from app.schemas.task import Task, TaskQuery, TaskStatus
from app.services.agent import (
    AgentThreadConflictError,
    TaskAgentService,
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
        raise AssertionError('parser must not run in stage three query tests')


def _query(
    *,
    scope: TimeScope,
    reference: str | None = None,
    statuses: set[TaskStatus] | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    raw: str | None = None,
    clarification_reason: ClarificationReason | None = None,
    question: str | None = None,
) -> IntentResult:
    return IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=1,
        reason='test query',
        task_reference=reference,
        query=TaskQueryIntent(
            time_scope=scope,
            statuses=statuses,
            start_at=start_at,
            end_at=end_at,
            raw_time_expression=raw,
        ),
        needs_clarification=clarification_reason is not None,
        clarification_reason=clarification_reason,
        clarification_question=question,
    )


class Harness:
    def __init__(self, responses: dict[str, IntentResult], key_prefix: str) -> None:
        self.now = NOW
        self.redis = FakeRedis(decode_responses=True)
        self.repository = RedisTaskRepository(self.redis, key_prefix=key_prefix)
        classifier = FakeIntentClassifier(responses=responses)
        self.graph = build_task_graph(
            GraphDependencies(
                parser=UnusedParser(),
                intent_service=IntentRecognitionService(classifier),
                task_repository=self.repository,
                clock=lambda: self.now,
            ),
            checkpointer=InMemorySaver(),
        )
        self.service = TaskAgentService(self.graph)
        self.request_number = 0

    async def chat(
        self,
        message: str,
        *,
        thread_id: str = 'thread-1',
        user_id: str = 'user-1',
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

    async def store(self, task: Task) -> None:
        await self.repository.create(
            task,
            idempotency_key=f'create-{task.id}',
        )

    async def close(self) -> None:
        await self.redis.aclose()


@pytest.mark.anyio
async def test_incomplete_query_is_completed_next_turn_and_cleared() -> None:
    harness = Harness(
        {
            '查看未完成任务': _query(
                scope=TimeScope.UNSPECIFIED,
                statuses=OPEN,
            ),
            '今天': _query(scope=TimeScope.TODAY),
        },
        'stage3:clarification',
    )
    try:
        await harness.store(
            Task(
                id='today',
                user_id='user-1',
                title='今天任务',
                deadline=datetime.fromisoformat('2026-08-03T15:00:00+08:00'),
            )
        )

        first = await harness.chat('查看未完成任务')
        second = await harness.chat('今天')

        assert first.status == 'needs_clarification'
        assert [task.id for task in second.tasks] == ['today']
        assert '今天' in second.message
        snapshot = await harness.graph.aget_state(
            harness.service._config('user-1', 'thread-1')
        )
        assert snapshot.values.get('pending_query_clarification') is None
        plan = snapshot.values['task_query_plan']
        assert set(plan['statuses']) == {'TODO', 'DOING', 'BLOCKED'}
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_ambiguous_time_continues_then_custom_completes() -> None:
    start = datetime.fromisoformat('2026-07-31T00:00:00+08:00')
    end = datetime.fromisoformat('2026-08-03T00:00:00+08:00')
    harness = Harness(
        {
            '查看未完成任务': _query(
                scope=TimeScope.UNSPECIFIED,
                statuses=OPEN,
            ),
            '前三天': _query(
                scope=TimeScope.CUSTOM,
                raw='前三天',
                clarification_reason=(
                    ClarificationReason.AMBIGUOUS_TIME_EXPRESSION
                ),
                question='请确认“前三天”的含义。',
            ),
            '过去三个完整自然日': _query(
                scope=TimeScope.CUSTOM,
                start_at=start,
                end_at=end,
                raw='过去三个完整自然日',
            ),
        },
        'stage3:ambiguous',
    )
    try:
        first = await harness.chat('查看未完成任务')
        ambiguous = await harness.chat('前三天')
        completed = await harness.chat('过去三个完整自然日')

        assert first.status == 'needs_clarification'
        assert ambiguous.status == 'needs_clarification'
        assert '前三天' in ambiguous.message
        assert completed.status == 'completed'
        snapshot = await harness.graph.aget_state(
            harness.service._config('user-1', 'thread-1')
        )
        assert snapshot.values['task_query_plan']['time_scope'] == 'CUSTOM'
        assert snapshot.values.get('pending_query_clarification') is None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_query_multiple_candidates_selects_second_without_write() -> None:
    harness = Harness(
        {
            '论文任务怎么样了': _query(
                scope=TimeScope.UNSPECIFIED,
                reference='论文任务',
            ),
        },
        'stage3:query-selection',
    )
    try:
        await harness.store(Task(id='task-1', user_id='user-1', title='论文任务'))
        await harness.store(
            Task(
                id='task-2',
                user_id='user-1',
                title='论文任务',
                status=TaskStatus.DOING,
            )
        )

        candidates = await harness.chat('论文任务怎么样了')
        selected = await harness.chat('第二个')

        assert candidates.status == 'needs_disambiguation'
        assert [task.id for task in candidates.candidates] == [
            'task-1',
            'task-2',
        ]
        assert selected.task is not None and selected.task.id == 'task-2'
        assert selected.pending_action is None
        stored = await harness.repository.list_tasks(
            TaskQuery(user_id='user-1')
        )
        assert all(task.version == 1 for task in stored.items)
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_update_multiple_candidates_selects_then_confirms() -> None:
    update_intent = IntentResult(
        intent=IntentType.UPDATE_TASK_STATUS,
        confidence=1,
        reason='test update',
        task_reference='论文任务',
        target_status=TaskStatus.DOING,
    )
    harness = Harness(
        {'把论文任务标记为进行中': update_intent},
        'stage3:update-selection',
    )
    try:
        await harness.store(Task(id='task-1', user_id='user-1', title='论文任务'))
        await harness.store(Task(id='task-2', user_id='user-1', title='论文任务'))

        candidates = await harness.chat('把论文任务标记为进行中')
        pending = await harness.chat('第二个')

        assert candidates.pending_action is None
        assert pending.status == 'awaiting_confirmation'
        before = await harness.repository.get(
            user_id='user-1',
            task_id='task-2',
        )
        assert before is not None and before.status == TaskStatus.TODO
        assert pending.pending_action is not None

        completed = await harness.service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-1',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )
        assert completed.task is not None
        assert completed.task.status == TaskStatus.DOING
        assert '进行中' in completed.message
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_query_clarification_can_be_cancelled_and_cleared() -> None:
    harness = Harness(
        {
            '查看未完成任务': _query(
                scope=TimeScope.UNSPECIFIED,
                statuses=OPEN,
            ),
        },
        'stage3:cancel',
    )
    try:
        await harness.chat('查看未完成任务')
        cancelled = await harness.chat('不用查了')

        assert cancelled.message == '已取消本次查询。'
        snapshot = await harness.graph.aget_state(
            harness.service._config('user-1', 'thread-1')
        )
        assert snapshot.values.get('pending_query_clarification') is None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_expired_clarification_does_not_merge_old_statuses() -> None:
    harness = Harness(
        {
            '查看未完成任务': _query(
                scope=TimeScope.UNSPECIFIED,
                statuses=OPEN,
            ),
            '今天': _query(scope=TimeScope.TODAY),
        },
        'stage3:expired',
    )
    try:
        await harness.chat('查看未完成任务')
        harness.now = NOW + timedelta(minutes=16)
        await harness.chat('今天')

        snapshot = await harness.graph.aget_state(
            harness.service._config('user-1', 'thread-1')
        )
        assert snapshot.values.get('pending_query_clarification') is None
        assert snapshot.values['task_query_plan']['statuses'] is None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_complete_new_query_replaces_old_clarification() -> None:
    harness = Harness(
        {
            '查看未完成任务': _query(
                scope=TimeScope.UNSPECIFIED,
                statuses=OPEN,
            ),
            '查看论文任务详情': _query(
                scope=TimeScope.UNSPECIFIED,
                reference='论文任务',
            ),
        },
        'stage3:new-request',
    )
    try:
        await harness.store(
            Task(id='paper', user_id='user-1', title='论文任务')
        )
        await harness.chat('查看未完成任务')
        response = await harness.chat('查看论文任务详情')

        assert response.task is not None and response.task.id == 'paper'
        snapshot = await harness.graph.aget_state(
            harness.service._config('user-1', 'thread-1')
        )
        assert snapshot.values.get('pending_query_clarification') is None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_invalid_selection_keeps_refreshed_candidates() -> None:
    harness = Harness(
        {
            '论文任务怎么样了': _query(
                scope=TimeScope.UNSPECIFIED,
                reference='论文任务',
            ),
        },
        'stage3:invalid-selection',
    )
    try:
        await harness.store(Task(id='task-1', user_id='user-1', title='论文任务'))
        await harness.store(Task(id='task-2', user_id='user-1', title='论文任务'))
        await harness.chat('论文任务怎么样了')

        invalid = await harness.chat('第三个')

        assert invalid.status == 'needs_disambiguation'
        assert len(invalid.candidates) == 2
        snapshot = await harness.graph.aget_state(
            harness.service._config('user-1', 'thread-1')
        )
        assert snapshot.values.get('pending_task_selection') is not None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_deleted_selected_candidate_fails_closed() -> None:
    harness = Harness(
        {
            '论文任务怎么样了': _query(
                scope=TimeScope.UNSPECIFIED,
                reference='论文任务',
            ),
        },
        'stage3:deleted-selection',
    )
    try:
        await harness.store(Task(id='task-1', user_id='user-1', title='论文任务'))
        await harness.store(Task(id='task-2', user_id='user-1', title='论文任务'))
        await harness.chat('论文任务怎么样了')
        await harness.redis.delete(
            harness.repository._task_key('user-1', 'task-2')
        )

        response = await harness.chat('第二个')

        assert response.pending_action is None
        assert '已发生变化或已不存在' in response.message
        snapshot = await harness.graph.aget_state(
            harness.service._config('user-1', 'thread-1')
        )
        assert snapshot.values.get('pending_task_selection') is None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_changed_candidate_version_fails_before_pending_action() -> None:
    update_intent = IntentResult(
        intent=IntentType.UPDATE_TASK_STATUS,
        confidence=1,
        reason='test update',
        task_reference='论文任务',
        target_status=TaskStatus.DOING,
    )
    harness = Harness(
        {'把论文任务标记为进行中': update_intent},
        'stage3:changed-selection',
    )
    try:
        await harness.store(Task(id='task-1', user_id='user-1', title='论文任务'))
        await harness.store(Task(id='task-2', user_id='user-1', title='论文任务'))
        await harness.chat('把论文任务标记为进行中')
        await harness.repository.update_status(
            user_id='user-1',
            task_id='task-2',
            target_status=TaskStatus.DOING,
            expected_version=1,
        )

        response = await harness.chat('第二个')

        assert response.pending_action is None
        assert '已发生变化或已不存在' in response.message
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_selection_does_not_cross_threads() -> None:
    harness = Harness(
        {
            '论文任务怎么样了': _query(
                scope=TimeScope.UNSPECIFIED,
                reference='论文任务',
            ),
        },
        'stage3:thread-isolation',
    )
    try:
        await harness.store(Task(id='task-1', user_id='user-1', title='论文任务'))
        await harness.store(Task(id='task-2', user_id='user-1', title='论文任务'))
        await harness.chat('论文任务怎么样了', thread_id='thread-1')

        other = await harness.chat('第二个', thread_id='thread-2')

        assert other.task is None
        assert other.candidates == []
        original = await harness.graph.aget_state(
            harness.service._config('user-1', 'thread-1')
        )
        assert original.values.get('pending_task_selection') is not None
    finally:
        await harness.close()



@pytest.mark.anyio
async def test_selection_does_not_cross_users_with_same_thread_id() -> None:
    harness = Harness(
        {
            '论文任务怎么样了': _query(
                scope=TimeScope.UNSPECIFIED,
                reference='论文任务',
            ),
        },
        'stage3:user-isolation',
    )
    try:
        await harness.store(Task(id='task-1', user_id='user-1', title='论文任务'))
        await harness.store(Task(id='task-2', user_id='user-1', title='论文任务'))
        await harness.chat('论文任务怎么样了')

        other = await harness.chat('第二个', user_id='user-2')

        assert other.task is None
        assert other.candidates == []
        original = await harness.graph.aget_state(
            harness.service._config('user-1', 'thread-1')
        )
        assert original.values.get('pending_task_selection') is not None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_pending_action_blocks_ordinary_selection_or_query_messages() -> None:
    update = IntentResult(
        intent=IntentType.UPDATE_TASK_STATUS,
        confidence=1,
        reason='update',
        task_reference='唯一任务',
        target_status=TaskStatus.DOING,
    )
    harness = Harness(
        {'把唯一任务标记为进行中': update},
        'stage3:pending-action-priority',
    )
    try:
        await harness.store(
            Task(id='only', user_id='user-1', title='唯一任务')
        )
        pending = await harness.chat('把唯一任务标记为进行中')
        assert pending.status == 'awaiting_confirmation'

        with pytest.raises(AgentThreadConflictError):
            await harness.chat('查看所有任务')
    finally:
        await harness.close()

