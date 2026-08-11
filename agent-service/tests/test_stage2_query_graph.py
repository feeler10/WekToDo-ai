from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis

from app.graph.builder import GraphDependencies, build_task_graph
from app.intent.enums import IntentType, TimeScope
from app.intent.models import IntentResult, TaskQueryIntent
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.subtask import SubtaskBatchCreate, SubtaskDraft
from app.schemas.task import Task, TaskPriority, TaskQuery, TaskStatus


NOW = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)


class UnusedParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        raise AssertionError('task parser must not be called for queries')


def _state(message: str = 'query') -> dict[str, object]:
    return {
        'user_id': 'user-1',
        'thread_id': 'thread-1',
        'request_id': 'request-1',
        'user_message': message,
        'timezone': 'Asia/Shanghai',
        'pending_action': None,
        'task_results': [],
        'candidate_tasks': [],
    }


async def _store(
    repository: RedisTaskRepository,
    task: Task,
) -> None:
    await repository.create(
        task,
        idempotency_key=f'create-{task.user_id}-{task.id}',
    )


def _graph(
    repository: RedisTaskRepository,
    intent_result: IntentResult,
):
    return build_task_graph(
        GraphDependencies(
            parser=UnusedParser(),
            intent_service=IntentRecognitionService(
                FakeIntentClassifier(intent_result)
            ),
            task_repository=repository,
            clock=lambda: NOW,
        )
    )


@pytest.mark.anyio
async def test_custom_query_combines_all_conditions_without_writing() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='stage2:graph-custom')
    start = datetime.fromisoformat('2026-08-02T00:00:00+08:00')
    end = datetime.fromisoformat('2026-08-05T00:00:00+08:00')
    try:
        tasks = [
            Task(
                id='included',
                user_id='user-1',
                title='未来任务',
                deadline=start,
                status=TaskStatus.DOING,
                ai_priority=TaskPriority.HIGH,
            ),
            Task(
                id='at-end',
                user_id='user-1',
                title='边界任务',
                deadline=end,
                status=TaskStatus.DOING,
                ai_priority=TaskPriority.HIGH,
            ),
            Task(
                id='wrong-status',
                user_id='user-1',
                title='完成任务',
                deadline=start,
                status=TaskStatus.DONE,
                ai_priority=TaskPriority.HIGH,
            ),
            Task(
                id='wrong-priority',
                user_id='user-1',
                title='低优先级任务',
                deadline=start,
                status=TaskStatus.DOING,
                ai_priority=TaskPriority.LOW,
            ),
        ]
        for task in tasks:
            await _store(repository, task)
        before = await repository.list_tasks(TaskQuery(user_id='user-1'))
        intent_result = IntentResult(
            intent=IntentType.QUERY_TASKS,
            confidence=1,
            reason='custom query',
            query=TaskQueryIntent(
                time_scope=TimeScope.CUSTOM,
                start_at=start,
                end_at=end,
                raw_time_expression='未来三天',
                statuses={TaskStatus.DOING},
                priorities={TaskPriority.HIGH},
            ),
        )

        result = await _graph(repository, intent_result).ainvoke(_state())
        after = await repository.list_tasks(TaskQuery(user_id='user-1'))

        assert [task['id'] for task in result['task_results']] == ['included']
        assert result['task_query_plan']['due_from'] == start.isoformat()
        assert result['task_query_plan']['due_to'] == end.isoformat()
        assert 'raw_time_expression' not in result['task_query_plan']
        assert result.get('pending_action') is None
        assert after.items == before.items
    finally:
        await redis.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ('titles', 'expected_selected', 'expected_candidates'),
    [
        (['论文实验'], 'task-1', []),
        (['论文实验', '论文实验'], None, ['task-1', 'task-2']),
        (['代码复查'], None, []),
    ],
)
async def test_specific_query_uses_matcher_without_pending_action(
    titles: list[str],
    expected_selected: str | None,
    expected_candidates: list[str],
) -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='stage2:graph-match')
    try:
        for index, title in enumerate(titles, start=1):
            await _store(
                repository,
                Task(
                    id=f'task-{index}',
                    user_id='user-1',
                    title=title,
                ),
            )
        await _store(
            repository,
            Task(id='foreign', user_id='user-2', title='论文实验'),
        )
        intent_result = IntentResult(
            intent=IntentType.QUERY_TASKS,
            confidence=1,
            reason='specific query',
            task_reference='论文实验',
            query=TaskQueryIntent(time_scope=TimeScope.UNSPECIFIED),
        )

        result = await _graph(repository, intent_result).ainvoke(_state())

        assert (
            result.get('selected_task') or {}
        ).get('id') == expected_selected
        assert [
            candidate['id'] for candidate in result['candidate_tasks']
        ] == expected_candidates
        assert result.get('pending_action') is None
        assert all(
            candidate['user_id'] == 'user-1'
            for candidate in result['candidate_tasks']
        )
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_explicit_subtask_query_reads_children_from_repository() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='stage2:subtask-query')
    try:
        await _store(
            repository,
            Task(id='parent', user_id='user-1', title='论文实验'),
        )
        await repository.create_subtasks_batch(
            SubtaskBatchCreate(
                user_id='user-1',
                parent_task_id='parent',
                expected_parent_version=1,
                items=[
                    SubtaskDraft(
                        step_key='run',
                        title='运行实验',
                        order=2,
                    ),
                    SubtaskDraft(
                        step_key='prepare',
                        title='准备数据',
                        order=1,
                    ),
                ],
            ),
            idempotency_key='create-subtasks',
        )
        intent_result = IntentResult(
            intent=IntentType.QUERY_TASKS,
            confidence=1,
            reason='specific subtask query',
            task_reference='论文实验',
            query=TaskQueryIntent(include_subtasks=True),
        )

        result = await _graph(repository, intent_result).ainvoke(_state())

        assert result['selected_task']['id'] == 'parent'
        assert '“论文实验”共有 2 个子任务' in result['final_response']
        assert result['final_response'].index('1. 准备数据') < (
            result['final_response'].index('2. 运行实验')
        )
    finally:
        await redis.aclose()
