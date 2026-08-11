from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.builder import GraphDependencies, build_task_graph
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest, AgentResponse
from app.schemas.task import TaskQuery
from app.services.agent import TaskAgentService
from app.services.task_draft_clarification import (
    format_task_collection_input,
    is_task_draft_collection_cancellation,
    looks_like_explicit_new_request,
)
from tests.intent_helpers import existing_flow_intent_service


NOW = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class SequenceParser:
    def __init__(self, outputs: list[Mapping[str, Any]]) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[str, str]] = []

    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        self.calls.append((user_message, timezone))
        if not self.outputs:
            raise AssertionError('unexpected parser call')
        return self.outputs.pop(0)


class Harness:
    def __init__(
        self,
        outputs: list[Mapping[str, Any]],
        *,
        key_prefix: str,
        max_rounds: int = 4,
        pending_ttl_seconds: int = 900,
    ) -> None:
        self.redis = FakeRedis(decode_responses=True)
        self.repository = RedisTaskRepository(
            self.redis,
            key_prefix=key_prefix,
        )
        self.parser = SequenceParser(outputs)
        self.clock = MutableClock()
        self.graph = build_task_graph(
            GraphDependencies(
                intent_service=existing_flow_intent_service(),
                parser=self.parser,
                task_repository=self.repository,
                clock=self.clock,
                pending_context_ttl_seconds=pending_ttl_seconds,
                task_draft_clarification_max_rounds=max_rounds,
            ),
            checkpointer=InMemorySaver(),
        )
        self.service = TaskAgentService(self.graph)
        self.request_number = 0

    async def chat(
        self,
        message: str,
        *,
        user_id: str = 'user-1',
        thread_id: str = 'thread-1',
    ) -> AgentResponse:
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

    async def tasks(self, *, user_id: str = 'user-1') -> list[object]:
        result = await self.repository.list_tasks(TaskQuery(user_id=user_id))
        return list(result.items)

    async def close(self) -> None:
        await self.redis.aclose()


def partial_title_draft() -> dict[str, object]:
    return {
        'description': '准备下周的汇报',
        'missing_fields': ['title'],
        'clarification_question': '这个任务叫什么？',
    }


@pytest.mark.anyio
async def test_collects_missing_title_then_confirms_before_single_write() -> None:
    harness = Harness(
        [
            partial_title_draft(),
            {
                'title': '完成项目周报',
                'description': '准备下周的汇报',
                'semantic_importance': 70,
            },
        ],
        key_prefix='draft-clarification:happy-path',
    )
    try:
        clarification = await harness.chat('帮我建一个准备下周汇报的任务')

        assert clarification.status == 'needs_clarification'
        assert clarification.message == '这个任务叫什么？'
        assert clarification.pending_action is None
        assert await harness.tasks() == []

        pending = await harness.chat('任务叫完成项目周报')

        assert pending.status == 'awaiting_confirmation'
        assert pending.task_draft is not None
        assert pending.task_draft.title == '完成项目周报'
        assert await harness.tasks() == []
        assert '[第1轮]' in harness.parser.calls[1][0]
        assert '[第2轮] 任务叫完成项目周报' in harness.parser.calls[1][0]

        assert pending.pending_action is not None
        completed = await harness.service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-1',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )

        assert completed.status == 'completed'
        stored = await harness.tasks()
        assert len(stored) == 1
        assert stored[0].title == '完成项目周报'
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_multiple_rounds_keep_context_and_later_correction_wins() -> None:
    harness = Harness(
        [
            partial_title_draft(),
            {
                'title': '初版周报',
                'missing_fields': ['deadline'],
                'clarification_question': '截止时间是什么时候？',
            },
            {
                'title': '最终版周报',
                'deadline': '2026-08-15T18:00:00+08:00',
            },
        ],
        key_prefix='draft-clarification:correction',
    )
    try:
        first = await harness.chat('创建一个周报任务')
        second = await harness.chat('先叫初版周报')
        pending = await harness.chat(
            '名称改为最终版周报，截止到8月15日18点'
        )

        assert first.status == 'needs_clarification'
        assert second.status == 'needs_clarification'
        assert pending.status == 'awaiting_confirmation'
        assert pending.task_draft is not None
        assert pending.task_draft.title == '最终版周报'
        third_input = harness.parser.calls[2][0]
        assert '[第1轮] 创建一个周报任务' in third_input
        assert '[第2轮] 先叫初版周报' in third_input
        assert '[第3轮] 名称改为最终版周报' in third_input
        assert await harness.tasks() == []
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_cancellation_clears_collection_without_calling_parser_again() -> None:
    harness = Harness(
        [partial_title_draft()],
        key_prefix='draft-clarification:cancel',
    )
    try:
        await harness.chat('创建一个任务')
        cancelled = await harness.chat('算了')

        assert cancelled.status == 'rejected'
        assert cancelled.message == '已取消本次任务创建。'
        assert len(harness.parser.calls) == 1
        assert await harness.tasks() == []
        snapshot = await harness.graph.aget_state(
            {'configurable': {'thread_id': 'user-1:thread-1'}}
        )
        assert snapshot.values.get('pending_task_draft_clarification') is None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_explicit_new_query_replaces_pending_draft() -> None:
    harness = Harness(
        [partial_title_draft()],
        key_prefix='draft-clarification:new-query',
    )
    try:
        await harness.chat('创建一个任务')
        queried = await harness.chat('查询我的任务')

        assert queried.status == 'completed'
        assert queried.tasks == []
        assert len(harness.parser.calls) == 1
        snapshot = await harness.graph.aget_state(
            {'configurable': {'thread_id': 'user-1:thread-1'}}
        )
        assert snapshot.values.get('pending_task_draft_clarification') is None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_collection_stops_at_configured_round_limit() -> None:
    harness = Harness(
        [partial_title_draft(), partial_title_draft(), partial_title_draft()],
        key_prefix='draft-clarification:max-rounds',
        max_rounds=2,
    )
    try:
        await harness.chat('创建一个任务')
        await harness.chat('还没想好')
        stopped = await harness.chat('再想想')

        assert stopped.status == 'rejected'
        assert '本次创建已停止' in stopped.message
        assert await harness.tasks() == []
        snapshot = await harness.graph.aget_state(
            {'configurable': {'thread_id': 'user-1:thread-1'}}
        )
        assert snapshot.values.get('pending_task_draft_clarification') is None
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_expired_collection_is_discarded_before_new_query() -> None:
    harness = Harness(
        [partial_title_draft()],
        key_prefix='draft-clarification:ttl',
        pending_ttl_seconds=60,
    )
    try:
        await harness.chat('创建一个任务')
        harness.clock.now += timedelta(seconds=61)

        queried = await harness.chat('查询我的任务')

        assert queried.status == 'completed'
        assert queried.tasks == []
        assert len(harness.parser.calls) == 1
        assert await harness.tasks() == []
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_pending_draft_is_isolated_by_user_and_thread() -> None:
    harness = Harness(
        [partial_title_draft()],
        key_prefix='draft-clarification:isolation',
    )
    try:
        pending = await harness.chat(
            '创建一个任务',
            user_id='user-1',
            thread_id='shared-name',
        )
        unrelated = await harness.chat(
            '查询我的任务',
            user_id='user-2',
            thread_id='shared-name',
        )
        cancelled = await harness.chat(
            '取消',
            user_id='user-1',
            thread_id='shared-name',
        )

        assert pending.status == 'needs_clarification'
        assert unrelated.status == 'completed'
        assert unrelated.tasks == []
        assert cancelled.status == 'rejected'
        assert cancelled.message == '已取消本次任务创建。'
        assert len(harness.parser.calls) == 1
    finally:
        await harness.close()


def test_collection_message_helpers_are_bounded_and_deterministic() -> None:
    combined = format_task_collection_input(['创建周报', '名称改为项目周报'])

    assert '[第1轮] 创建周报' in combined
    assert '[第2轮] 名称改为项目周报' in combined
    assert is_task_draft_collection_cancellation(' 取消创建！ ')
    assert not is_task_draft_collection_cancellation('取消明天的任务')
    assert looks_like_explicit_new_request('查询我的任务')
    assert not looks_like_explicit_new_request('任务名称叫查看论文')
