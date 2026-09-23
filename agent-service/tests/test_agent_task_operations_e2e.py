from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.builder import GraphDependencies, build_task_graph
from tests.intent_helpers import existing_flow_intent_service
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest, AgentResponse
from app.schemas.task import Task, TaskQuery, TaskStatus
from app.services.agent import TaskAgentService


NOW = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)


class FixedParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        return {
            'title': '创建后可查询任务',
            'deadline': '2026-08-01T23:00:00+08:00',
            'deadline_score': 60,
            'semantic_importance': 60,
        }


class Harness:
    def __init__(self, key_prefix: str) -> None:
        self.redis = FakeRedis(decode_responses=True)
        self.repository = RedisTaskRepository(
            self.redis,
            key_prefix=key_prefix,
        )
        graph = build_task_graph(
            GraphDependencies(
                intent_service=existing_flow_intent_service(),
                parser=FixedParser(),
                task_repository=self.repository,
                clock=lambda: NOW,
            ),
            checkpointer=InMemorySaver(),
        )
        self.service = TaskAgentService(graph)
        self._request_number = 0

    async def chat(
        self,
        message: str,
        *,
        user_id: str = 'user-1',
        thread_id: str | None = None,
    ) -> AgentResponse:
        self._request_number += 1
        suffix = str(self._request_number)
        return await self.service.chat(
            AgentChatRequest(
                user_id=user_id,
                thread_id=thread_id or f'thread-{suffix}',
                request_id=f'request-{suffix}',
                message=message,
                timezone='Asia/Shanghai',
            )
        )

    async def confirm(
        self,
        response: AgentResponse,
        *,
        user_id: str = 'user-1',
        action: str = 'approve',
    ) -> AgentResponse:
        assert response.pending_action is not None
        return await self.service.confirm(
            AgentConfirmRequest(
                user_id=user_id,
                thread_id=response.thread_id,
                action_id=response.pending_action.id,
                action=action,
            )
        )

    async def store(
        self,
        task_id: str,
        title: str,
        *,
        user_id: str = 'user-1',
        deadline: datetime | None = None,
        status: TaskStatus = TaskStatus.TODO,
    ) -> Task:
        task = Task(
            id=task_id,
            user_id=user_id,
            title=title,
            deadline=deadline,
            status=status,
        )
        return await self.repository.create(
            task,
            idempotency_key=f'create-{user_id}-{task_id}',
        )

    async def close(self) -> None:
        await self.redis.aclose()


@pytest.mark.anyio
async def test_create_then_query_reads_created_task_from_redis() -> None:
    harness = Harness('e2e:create-query')
    try:
        pending = await harness.chat('创建一个今天要完成的任务')
        created = await harness.confirm(pending)
        queried = await harness.chat('查询我的任务')

        assert created.task is not None
        assert queried.status == 'completed'
        assert [task.id for task in queried.tasks] == [created.task.id]
        stored = await harness.repository.get(
            user_id='user-1',
            task_id=created.task.id,
        )
        assert stored == queried.tasks[0]
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_today_query_returns_only_open_tasks_due_today() -> None:
    harness = Harness('e2e:today')
    try:
        await harness.store(
            'today',
            '今天任务',
            deadline=datetime(2026, 8, 1, 15, tzinfo=timezone.utc),
        )
        await harness.store(
            'tomorrow',
            '明天任务',
            deadline=datetime(2026, 8, 2, 15, tzinfo=timezone.utc),
        )
        await harness.store(
            'done',
            '今天已完成',
            deadline=datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
            status=TaskStatus.DONE,
        )

        response = await harness.chat('今天有哪些任务？')

        assert [task.id for task in response.tasks] == ['today']
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_overdue_query_returns_real_open_overdue_tasks() -> None:
    harness = Harness('e2e:overdue')
    try:
        await harness.store(
            'overdue',
            '逾期任务',
            deadline=datetime(2026, 7, 31, 12, tzinfo=timezone.utc),
            status=TaskStatus.DOING,
        )
        await harness.store(
            'future',
            '未来任务',
            deadline=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
        )

        response = await harness.chat('有哪些逾期任务？')

        assert [task.id for task in response.tasks] == ['overdue']
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_unique_task_status_update_requires_confirmation() -> None:
    harness = Harness('e2e:update')
    try:
        task = await harness.store('unique', '唯一任务')

        pending = await harness.chat('把唯一任务标记为进行中')
        before = await harness.repository.get(
            user_id='user-1',
            task_id=task.id,
        )
        assert pending.status == 'awaiting_confirmation'
        assert before is not None and before.status == TaskStatus.TODO

        completed = await harness.confirm(pending)

        assert completed.task is not None
        assert completed.task.status == TaskStatus.DOING
        assert completed.task.version == 2
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_duplicate_titles_return_candidates_without_update() -> None:
    harness = Harness('e2e:duplicates')
    try:
        await harness.store('duplicate-1', '重复任务')
        await harness.store('duplicate-2', '重复任务')

        response = await harness.chat('把重复任务标记为进行中')

        assert response.status == 'needs_disambiguation'
        assert {task.id for task in response.candidates} == {
            'duplicate-1',
            'duplicate-2',
        }
        assert response.pending_action is None
        stored = await harness.repository.list_tasks(
            TaskQuery(user_id='user-1')
        )
        assert all(task.status == TaskStatus.TODO for task in stored.items)
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_illegal_status_transition_is_rejected_before_confirmation() -> None:
    harness = Harness('e2e:illegal')
    try:
        task = await harness.store('illegal', '非法任务')

        response = await harness.chat('非法任务已经完成了')

        assert response.status == 'error'
        assert response.message == '当前任务状态不支持此操作。'
        assert response.error is not None
        assert response.error.code == 'invalid_status_transition'
        assert response.pending_action is None
        stored = await harness.repository.get(
            user_id='user-1',
            task_id=task.id,
        )
        assert stored is not None and stored.status == TaskStatus.TODO
    finally:
        await harness.close()


@pytest.mark.anyio
async def test_queries_and_updates_are_isolated_by_user() -> None:
    harness = Harness('e2e:isolation')
    try:
        foreign = await harness.store(
            'foreign',
            '他人任务',
            user_id='user-b',
        )

        query = await harness.chat('查询我的任务', user_id='user-a')
        update = await harness.chat(
            '把他人任务标记为进行中',
            user_id='user-a',
        )

        assert query.tasks == []
        assert update.task is None
        assert update.pending_action is None
        stored = await harness.repository.get(
            user_id='user-b',
            task_id=foreign.id,
        )
        assert stored is not None and stored.status == TaskStatus.TODO
    finally:
        await harness.close()
