from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.builder import GraphDependencies, build_task_graph
from app.intent.enums import IntentType
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest
from app.schemas.subtask import SubtaskBatchCreate
from app.schemas.task import Task, TaskStatus
from app.schemas.task_deletion import TaskDeleteParseResult
from app.services.agent import TaskAgentService


NOW = datetime(2026, 8, 11, 2, tzinfo=timezone.utc)


class UnusedTaskParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        raise AssertionError('create parser must not be called')


class FixedDeleteParser:
    def __init__(self, result: TaskDeleteParseResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, datetime]] = []

    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
        current_datetime: datetime,
    ) -> Mapping[str, Any]:
        self.calls.append((user_message, timezone, current_datetime))
        return self.result.model_dump(mode='json')


async def _harness(
    key_prefix: str,
    parsed: TaskDeleteParseResult,
) -> tuple[FakeRedis, RedisTaskRepository, TaskAgentService, FixedDeleteParser]:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix=key_prefix)
    delete_parser = FixedDeleteParser(parsed)
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedTaskParser(),
            task_delete_parser=delete_parser,
            intent_service=IntentRecognitionService(
                FakeIntentClassifier(
                    intent=IntentType.DELETE_TASK,
                    reason='测试自然语言批量删除',
                )
            ),
            task_repository=repository,
            clock=lambda: NOW,
        ),
        checkpointer=InMemorySaver(),
    )
    return redis, repository, TaskAgentService(graph), delete_parser


def _request(message: str, *, thread_id: str) -> AgentChatRequest:
    return AgentChatRequest(
        user_id='user-1',
        thread_id=thread_id,
        request_id=f'request-{thread_id}',
        message=message,
        timezone='Asia/Shanghai',
    )


async def _create_parent_with_children(
    repository: RedisTaskRepository,
    *,
    parent_id: str,
    parent_title: str,
    child_titles: list[str],
) -> tuple[Task, list[Task]]:
    parent = await repository.create(
        Task(id=parent_id, user_id='user-1', title=parent_title),
        idempotency_key=f'create:{parent_id}',
    )
    result = await repository.create_subtasks_batch(
        SubtaskBatchCreate.model_validate(
            {
                'user_id': 'user-1',
                'parent_task_id': parent.id,
                'expected_parent_version': parent.version,
                'items': [
                    {
                        'step_key': f'step-{index}',
                        'title': title,
                        'order': index,
                    }
                    for index, title in enumerate(child_titles, start=1)
                ],
            }
        ),
        idempotency_key=f'children:{parent_id}',
    )
    return result.parent_task, result.subtasks


@pytest.mark.anyio
async def test_keyword_delete_previews_all_matches_then_deletes_atomically() -> None:
    parsed = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL'},
            'keywords': ['论文'],
            'match_mode': 'CONTAINS',
            'delete_all_matches': True,
            'reason': '删除所有包含论文的任务',
        }
    )
    redis, repository, service, parser = await _harness(
        'delete:graph:keyword', parsed
    )
    try:
        tasks = [
            Task(id='paper-title', user_id='user-1', title='论文实验'),
            Task(
                id='paper-description',
                user_id='user-1',
                title='整理资料',
                description='完成论文参考文献整理',
            ),
            Task(id='other', user_id='user-1', title='购买牛奶'),
        ]
        for task in tasks:
            await repository.create(task, idempotency_key=f'create:{task.id}')

        pending = await service.chat(
            _request('删除所有有关论文的代办', thread_id='keyword')
        )

        assert pending.status == 'awaiting_confirmation'
        assert pending.pending_action is not None
        assert pending.pending_action.action_type == 'delete_tasks_batch'
        assert {task.id for task in pending.deletion_tasks} == {
            'paper-title',
            'paper-description',
        }
        assert parser.calls == [
            ('删除所有有关论文的代办', 'Asia/Shanghai', NOW)
        ]

        completed = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='keyword',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )
        assert set(completed.deleted_task_ids) == {
            'paper-title',
            'paper-description',
        }
        assert await repository.get(user_id='user-1', task_id='other')
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_custom_date_range_is_a_deterministic_filter() -> None:
    custom = TaskDeleteParseResult.model_validate(
        {
            'query': {
                'time_scope': 'CUSTOM',
                'start_at': '2026-08-01T00:00:00+08:00',
                'end_at': '2026-08-11T00:00:00+08:00',
            },
            'delete_all_matches': True,
            'reason': '指定任意日期范围',
        }
    )
    redis, repository, service, _parser = await _harness(
        'delete:graph:custom', custom
    )
    try:
        await repository.create(
            Task(
                id='inside',
                user_id='user-1',
                title='区间内',
                deadline=datetime(2026, 8, 5, 12, tzinfo=timezone.utc),
            ),
            idempotency_key='inside',
        )
        await repository.create(
            Task(
                id='outside',
                user_id='user-1',
                title='区间外',
                deadline=datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
            ),
            idempotency_key='outside',
        )

        pending = await service.chat(
            _request('删除八月一日到十日的任务', thread_id='custom')
        )
        assert [task.id for task in pending.deletion_tasks] == ['inside']
        assert pending.pending_action is not None
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_parent_scope_only_matches_direct_children_of_selected_parent() -> None:
    parsed = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL'},
            'target_scope': 'DIRECT_CHILDREN',
            'parent_reference': '完成扩散模型论文实验',
            'task_references': ['结果分析与实验报告撰写任务'],
            'match_mode': 'EXACT',
            'reason': '删除指定父任务下的指定子任务',
        }
    )
    redis, repository, service, _parser = await _harness(
        'delete:graph:parent-scope', parsed
    )
    try:
        _parent, scoped_children = await _create_parent_with_children(
            repository,
            parent_id='parent-paper',
            parent_title='完成扩散模型论文实验',
            child_titles=[
                '结果分析与实验报告撰写任务',
                '准备数据',
                '训练模型',
            ],
        )
        _other_parent, other_children = await _create_parent_with_children(
            repository,
            parent_id='parent-other',
            parent_title='另一个实验',
            child_titles=[
                '结果分析与实验报告撰写任务',
                '清洗数据',
                '复现实验',
            ],
        )
        scoped_target = next(
            task
            for task in scoped_children
            if task.title == '结果分析与实验报告撰写任务'
        )
        other_target = next(
            task
            for task in other_children
            if task.title == '结果分析与实验报告撰写任务'
        )

        pending = await service.chat(
            _request(
                '删除完成扩散模型论文实验中的结果分析与实验报告撰写任务',
                thread_id='parent-scope',
            )
        )

        assert pending.pending_action is not None
        assert [task.id for task in pending.deletion_tasks] == [scoped_target.id]
        completed = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='parent-scope',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )
        assert completed.deleted_task_ids == [scoped_target.id]
        assert await repository.get(
            user_id='user-1', task_id=other_target.id
        )
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_parent_scope_can_preview_all_direct_children() -> None:
    parsed = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL'},
            'target_scope': 'DIRECT_CHILDREN',
            'parent_reference': '论文实验',
            'delete_all_matches': True,
            'reason': '删除父任务下全部直接子任务',
        }
    )
    redis, repository, service, _parser = await _harness(
        'delete:graph:all-children', parsed
    )
    try:
        _parent, children = await _create_parent_with_children(
            repository,
            parent_id='parent',
            parent_title='论文实验',
            child_titles=['步骤一', '步骤二', '步骤三'],
        )

        pending = await service.chat(
            _request('删除论文实验下所有子任务', thread_id='all-children')
        )

        assert pending.pending_action is not None
        assert {task.id for task in pending.deletion_tasks} == {
            task.id for task in children
        }
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_missing_reference_blocks_entire_multi_target_delete() -> None:
    parsed = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL'},
            'task_references': ['存在任务', '不存在任务'],
            'delete_all_matches': True,
            'reason': '删除两个指定任务',
        }
    )
    redis, repository, service, _parser = await _harness(
        'delete:graph:missing-reference', parsed
    )
    try:
        await repository.create(
            Task(id='existing', user_id='user-1', title='存在任务'),
            idempotency_key='existing',
        )

        response = await service.chat(
            _request('删除存在任务和不存在任务', thread_id='missing')
        )

        assert response.pending_action is None
        assert response.deletion_tasks == []
        assert '不会部分删除' in response.message
        assert await repository.get(user_id='user-1', task_id='existing')
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_ambiguous_reference_is_selected_before_batch_preview() -> None:
    parsed = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL'},
            'task_references': ['重复任务', '唯一任务'],
            'delete_all_matches': True,
            'reason': '删除两个指定任务',
        }
    )
    redis, repository, service, parser = await _harness(
        'delete:graph:reference-selection', parsed
    )
    try:
        for task_id, title in (
            ('duplicate-1', '重复任务'),
            ('duplicate-2', '重复任务'),
            ('unique', '唯一任务'),
        ):
            await repository.create(
                Task(id=task_id, user_id='user-1', title=title),
                idempotency_key=task_id,
            )

        candidates = await service.chat(
            _request('删除重复任务和唯一任务', thread_id='selection')
        )
        assert candidates.status == 'needs_disambiguation'
        assert {task.id for task in candidates.candidates} == {
            'duplicate-1',
            'duplicate-2',
        }
        assert candidates.pending_action is None

        pending = await service.chat(
            _request('duplicate-1', thread_id='selection')
        )
        assert pending.status == 'awaiting_confirmation'
        assert pending.pending_action is not None
        assert {task.id for task in pending.deletion_tasks} == {
            'duplicate-1',
            'unique',
        }
        assert len(parser.calls) == 1
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_ambiguous_parent_is_selected_before_scoping_children() -> None:
    parsed = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL'},
            'target_scope': 'DIRECT_CHILDREN',
            'parent_reference': '同名父任务',
            'task_references': ['目标子任务'],
            'reason': '同名父任务下的指定子任务',
        }
    )
    redis, repository, service, parser = await _harness(
        'delete:graph:parent-selection', parsed
    )
    try:
        _first_parent, first_children = await _create_parent_with_children(
            repository,
            parent_id='parent-1',
            parent_title='同名父任务',
            child_titles=['目标子任务', '第一辅助', '第二辅助'],
        )
        _second_parent, second_children = await _create_parent_with_children(
            repository,
            parent_id='parent-2',
            parent_title='同名父任务',
            child_titles=['目标子任务', '第三辅助', '第四辅助'],
        )
        first_target = next(
            task for task in first_children if task.title == '目标子任务'
        )
        second_target = next(
            task for task in second_children if task.title == '目标子任务'
        )

        parents = await service.chat(
            _request('删除同名父任务下的目标子任务', thread_id='parent-select')
        )
        assert parents.status == 'needs_disambiguation'
        assert {task.id for task in parents.candidates} == {
            'parent-1',
            'parent-2',
        }

        pending = await service.chat(
            _request('parent-2', thread_id='parent-select')
        )
        assert pending.pending_action is not None
        assert [task.id for task in pending.deletion_tasks] == [second_target.id]
        assert first_target.id != second_target.id
        assert len(parser.calls) == 1
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_multiple_ambiguous_references_are_resolved_one_by_one() -> None:
    parsed = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL'},
            'task_references': ['任务 A', '任务 B'],
            'delete_all_matches': True,
            'reason': '两个引用都存在多候选',
        }
    )
    redis, repository, service, parser = await _harness(
        'delete:graph:sequential-selection', parsed
    )
    try:
        for task_id, title in (
            ('a-1', '任务 A'),
            ('a-2', '任务 A'),
            ('b-1', '任务 B'),
            ('b-2', '任务 B'),
        ):
            await repository.create(
                Task(id=task_id, user_id='user-1', title=title),
                idempotency_key=task_id,
            )

        first = await service.chat(
            _request('删除任务 A 和任务 B', thread_id='sequential')
        )
        assert {task.id for task in first.candidates} == {'a-1', 'a-2'}

        second = await service.chat(
            _request('a-1', thread_id='sequential')
        )
        assert second.status == 'needs_disambiguation'
        assert {task.id for task in second.candidates} == {'b-1', 'b-2'}

        pending = await service.chat(
            _request('b-2', thread_id='sequential')
        )
        assert pending.pending_action is not None
        assert {task.id for task in pending.deletion_tasks} == {'a-1', 'b-2'}
        assert len(parser.calls) == 1
    finally:
        await redis.aclose()



@pytest.mark.anyio
async def test_cancelled_status_is_a_deterministic_filter() -> None:
    cancelled = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL', 'statuses': ['CANCELLED']},
            'delete_all_matches': True,
            'reason': '所有已取消任务',
        }
    )
    redis, repository, service, _parser = await _harness(
        'delete:graph:cancelled', cancelled
    )
    try:
        await repository.create(
            Task(
                id='cancelled',
                user_id='user-1',
                title='已取消',
                status=TaskStatus.CANCELLED,
            ),
            idempotency_key='cancelled',
        )
        await repository.create(
            Task(id='todo', user_id='user-1', title='待办'),
            idempotency_key='todo',
        )
        pending = await service.chat(
            _request('删除所有被取消的代办', thread_id='cancelled')
        )
        assert [task.id for task in pending.deletion_tasks] == ['cancelled']
    finally:
        await redis.aclose()
