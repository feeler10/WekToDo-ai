from datetime import datetime, timedelta, timezone

import pytest
from fakeredis.aioredis import FakeRedis
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.builder import GraphDependencies, build_task_graph
from app.intent.enums import IntentType, TimeScope
from app.intent.models import IntentResult, TaskQueryIntent
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest, AgentResponse
from app.schemas.task import Task, TaskUpdate
from app.schemas.task_attribute_update import (
    TaskFieldChange,
    TaskFieldName,
    TaskFieldOperation,
    TaskUpdateParseResult,
)
from app.services.agent import TaskAgentService


NOW = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class UnusedCreateParser:
    async def parse(self, user_message: str, *, timezone: str) -> object:
        raise AssertionError('create parser must not run')


class SequenceUpdateParser:
    def __init__(self, outputs: list[TaskUpdateParseResult]) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[str, str, int]] = []

    async def parse(
        self,
        user_message: str,
        *,
        current_task: Task,
        timezone: str,
        current_datetime: datetime,
    ) -> dict[str, object]:
        self.calls.append(
            (user_message, current_task.id, current_task.version)
        )
        if not self.outputs:
            raise AssertionError('unexpected update parser call')
        return self.outputs.pop(0).model_dump(mode='json')


class Harness:
    def __init__(
        self,
        outputs: list[TaskUpdateParseResult],
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
        self.parser = SequenceUpdateParser(outputs)
        self.clock = MutableClock()
        update_intent = IntentResult(
            intent=IntentType.UPDATE_TASK,
            confidence=1,
            reason='modify water task',
            task_reference='接水任务',
        )
        query_intent = IntentResult(
            intent=IntentType.QUERY_TASKS,
            confidence=1,
            reason='query tasks',
            query=TaskQueryIntent(time_scope=TimeScope.ALL),
        )
        intent_service = IntentRecognitionService(
            FakeIntentClassifier(
                result=update_intent,
                responses={'查询我的任务': query_intent},
            )
        )
        self.graph = build_task_graph(
            GraphDependencies(
                parser=UnusedCreateParser(),
                task_update_parser=self.parser,
                intent_service=intent_service,
                task_repository=self.repository,
                clock=self.clock,
                pending_context_ttl_seconds=pending_ttl_seconds,
                task_update_clarification_max_rounds=max_rounds,
            ),
            checkpointer=InMemorySaver(),
        )
        self.service = TaskAgentService(self.graph)
        self.request_number = 0

    async def seed(
        self,
        *,
        user_id: str = 'user-1',
        task_id: str = 'water',
    ) -> Task:
        return await self.repository.create(
            Task(
                id=task_id,
                user_id=user_id,
                title='接水任务',
            ),
            idempotency_key=f'seed-{user_id}-{task_id}',
        )

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

    async def close(self) -> None:
        await self.redis.aclose()


def clarification(question: str) -> TaskUpdateParseResult:
    return TaskUpdateParseResult(
        changes=[],
        needs_clarification=True,
        clarification_question=question,
        reason='修改信息不完整',
    )


def title_change(title: str) -> TaskUpdateParseResult:
    return TaskUpdateParseResult(
        changes=[
            TaskFieldChange(
                field=TaskFieldName.TITLE,
                operation=TaskFieldOperation.SET,
                value=title,
            )
        ],
        reason='修改标题',
    )


@pytest.mark.anyio
async def test_field_then_value_resumes_update_and_requires_confirmation() -> None:
    harness = Harness(
        [
            clarification('请问您想修改接水任务的哪些内容？'),
            clarification('您想把标题修改成什么？'),
            title_change('每天早上接水'),
        ],
        key_prefix='update-clarification:field-value',
    )
    try:
        await harness.seed()

        first = await harness.chat('修改接水任务')
        second = await harness.chat('标题')
        pending = await harness.chat('改成每天早上接水')
        before = await harness.repository.get(
            user_id='user-1',
            task_id='water',
        )

        assert first.status == 'needs_clarification'
        assert second.status == 'needs_clarification'
        assert second.message == '您想把标题修改成什么？'
        assert pending.status == 'awaiting_confirmation'
        assert pending.pending_action is not None
        assert before is not None
        assert before.title == '接水任务'
        assert before.version == 1
        assert '[第1轮] 修改接水任务' in harness.parser.calls[2][0]
        assert '[第2轮] 标题' in harness.parser.calls[2][0]
        assert '[第3轮] 改成每天早上接水' in harness.parser.calls[2][0]

        completed = await harness.service.confirm(
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
        await harness.close()


@pytest.mark.anyio
async def test_update_collection_can_be_cancelled_without_second_parse() -> None:
    harness = Harness(
        [clarification('你想修改什么？')],
        key_prefix='update-clarification:cancel',
    )
    try:
        await harness.seed()
        await harness.chat('修改接水任务')

        cancelled = await harness.chat('算了')
        task = await harness.repository.get(
            user_id='user-1',
            task_id='water',
        )

        assert cancelled.status == 'rejected'
        assert cancelled.message == '已取消本次任务修改。'
        assert len(harness.parser.calls) == 1
        assert task is not None and task.version == 1
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_explicit_query_replaces_pending_update() -> None:
    harness = Harness(
        [clarification('你想修改什么？')],
        key_prefix='update-clarification:query',
    )
    try:
        await harness.seed()
        await harness.chat('修改接水任务')

        queried = await harness.chat('查询我的任务')

        assert queried.status == 'completed'
        assert [task.id for task in queried.tasks] == ['water']
        assert len(harness.parser.calls) == 1
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_version_change_stops_stale_update_collection() -> None:
    harness = Harness(
        [clarification('你想修改什么？')],
        key_prefix='update-clarification:version',
    )
    try:
        await harness.seed()
        await harness.chat('修改接水任务')
        await harness.repository.update(
            user_id='user-1',
            task_id='water',
            update=TaskUpdate(
                user_id='user-1',
                expected_version=1,
                title='外部修改后的标题',
            ),
            idempotency_key='external-update',
        )

        stopped = await harness.chat('标题')

        assert stopped.status == 'rejected'
        assert '发生变化' in stopped.message
        assert len(harness.parser.calls) == 1
        task = await harness.repository.get(
            user_id='user-1',
            task_id='water',
        )
        assert task is not None
        assert task.title == '外部修改后的标题'
        assert task.version == 2
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_update_collection_stops_at_round_limit() -> None:
    harness = Harness(
        [
            clarification('你想修改什么？'),
            clarification('请继续补充。'),
            clarification('请继续补充。'),
        ],
        key_prefix='update-clarification:max-rounds',
        max_rounds=2,
    )
    try:
        await harness.seed()
        await harness.chat('修改接水任务')
        await harness.chat('标题')

        stopped = await harness.chat('还没想好')

        assert stopped.status == 'rejected'
        assert '本次修改已停止' in stopped.message
        task = await harness.repository.get(
            user_id='user-1',
            task_id='water',
        )
        assert task is not None and task.version == 1
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_expired_update_collection_is_discarded() -> None:
    harness = Harness(
        [clarification('你想修改什么？')],
        key_prefix='update-clarification:ttl',
        pending_ttl_seconds=60,
    )
    try:
        await harness.seed()
        await harness.chat('修改接水任务')
        harness.clock.now += timedelta(seconds=61)

        queried = await harness.chat('查询我的任务')

        assert queried.status == 'completed'
        assert len(harness.parser.calls) == 1
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_update_collection_is_isolated_by_user_and_thread() -> None:
    harness = Harness(
        [clarification('你想修改什么？')],
        key_prefix='update-clarification:isolation',
    )
    try:
        await harness.seed(user_id='user-1')
        await harness.seed(user_id='user-2')
        first = await harness.chat(
            '修改接水任务',
            user_id='user-1',
            thread_id='shared-thread',
        )
        unrelated = await harness.chat(
            '查询我的任务',
            user_id='user-2',
            thread_id='shared-thread',
        )
        cancelled = await harness.chat(
            '取消',
            user_id='user-1',
            thread_id='shared-thread',
        )

        assert first.status == 'needs_clarification'
        assert unrelated.status == 'completed'
        assert cancelled.status == 'rejected'
        assert len(harness.parser.calls) == 1
    finally:
        await harness.close()
