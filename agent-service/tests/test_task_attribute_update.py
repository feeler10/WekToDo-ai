from datetime import datetime, timezone

import pytest
from fakeredis.aioredis import FakeRedis
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.graph.builder import GraphDependencies, build_task_graph
from app.graph.task_update_parser import TASK_UPDATE_SYSTEM_PROMPT
from app.intent.enums import IntentType
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.agent import AgentChatRequest, AgentConfirmRequest
from app.schemas.task import Task, TaskPriority, TaskUpdate
from app.schemas.task_attribute_update import (
    TaskFieldChange,
    TaskFieldName,
    TaskFieldOperation,
    TaskUpdateParseResult,
)
from app.services.agent import TaskAgentService
from app.services.task_attribute_update import build_task_update


NOW = datetime(2026, 8, 10, 2, tzinfo=timezone.utc)


class UnusedCreateParser:
    async def parse(self, user_message: str, *, timezone: str) -> dict[str, object]:
        raise AssertionError('Create parser should not be called')


class FixedUpdateParser:
    def __init__(self, result: TaskUpdateParseResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, str]] = []

    async def parse(
        self,
        user_message: str,
        *,
        current_task: Task,
        timezone: str,
        current_datetime: datetime,
    ) -> dict[str, object]:
        self.calls.append((user_message, current_task.id, timezone))
        return self.result.model_dump(mode='json')


def update_intent_service(reference: str) -> IntentRecognitionService:
    return IntentRecognitionService(
        FakeIntentClassifier(
            intent=IntentType.UPDATE_TASK,
            task_reference=reference,
            reason='测试属性修改',
        )
    )


def test_update_prompt_strips_title_instruction_words() -> None:
    assert '新标题值是 X' in TASK_UPDATE_SYSTEM_PROMPT
    assert '不能把“改成”' in TASK_UPDATE_SYSTEM_PROMPT


def test_update_parse_result_rejects_duplicate_fields() -> None:
    with pytest.raises(ValidationError, match='only be changed once'):
        TaskUpdateParseResult(
            changes=[
                TaskFieldChange(
                    field=TaskFieldName.TITLE,
                    operation=TaskFieldOperation.SET,
                    value='标题一',
                ),
                TaskFieldChange(
                    field=TaskFieldName.TITLE,
                    operation=TaskFieldOperation.SET,
                    value='标题二',
                ),
            ],
            reason='重复字段',
        )


def test_build_task_update_preserves_clear_operation() -> None:
    parsed = TaskUpdateParseResult(
        changes=[
            TaskFieldChange(
                field=TaskFieldName.DEADLINE,
                operation=TaskFieldOperation.CLEAR,
            ),
            TaskFieldChange(
                field=TaskFieldName.USER_PRIORITY,
                operation=TaskFieldOperation.CLEAR,
            ),
        ],
        reason='清空截止时间和手动优先级',
    )

    update = build_task_update(parsed, user_id='user-1', expected_version=3)

    assert update.model_dump(exclude_unset=True) == {
        'user_id': 'user-1',
        'expected_version': 3,
        'deadline': None,
        'user_priority': None,
    }


def test_clear_description_uses_empty_string_required_by_task_entity() -> None:
    parsed = TaskUpdateParseResult(
        changes=[
            TaskFieldChange(
                field=TaskFieldName.DESCRIPTION,
                operation=TaskFieldOperation.CLEAR,
            )
        ],
        reason='清空描述',
    )

    update = build_task_update(parsed, user_id='user-1', expected_version=1)

    assert update.model_dump(exclude_unset=True)['description'] == ''


@pytest.mark.anyio
async def test_attribute_update_requires_confirmation_and_updates_redis() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='attribute:e2e')
    parser = FixedUpdateParser(
        TaskUpdateParseResult(
            changes=[
                TaskFieldChange(
                    field=TaskFieldName.TITLE,
                    operation=TaskFieldOperation.SET,
                    value='完成最终实验',
                ),
                TaskFieldChange(
                    field=TaskFieldName.DEADLINE,
                    operation=TaskFieldOperation.SET,
                    value='2026-08-14T23:59:59+08:00',
                ),
                TaskFieldChange(
                    field=TaskFieldName.USER_PRIORITY,
                    operation=TaskFieldOperation.SET,
                    value='URGENT',
                ),
            ],
            reason='修改标题、截止时间和优先级',
        )
    )
    task = Task(
        id='paper',
        user_id='user-1',
        title='论文任务',
        ai_priority=TaskPriority.HIGH,
    )
    try:
        await repository.create(task, idempotency_key='seed-paper')
        graph = build_task_graph(
            GraphDependencies(
                parser=UnusedCreateParser(),
                task_update_parser=parser,
                intent_service=update_intent_service('论文任务'),
                task_repository=repository,
                clock=lambda: NOW,
            ),
            checkpointer=InMemorySaver(),
        )
        service = TaskAgentService(graph)
        pending = await service.chat(
            AgentChatRequest(
                user_id='user-1',
                thread_id='thread-update',
                request_id='request-update',
                message='把论文任务改名并调整截止时间和优先级',
                timezone='Asia/Shanghai',
            )
        )
        before = await repository.get(user_id='user-1', task_id='paper')

        assert pending.status == 'awaiting_confirmation'
        assert pending.pending_action is not None
        assert pending.pending_action.action_type == 'update_task'
        assert before is not None and before.title == '论文任务'

        completed = await service.confirm(
            AgentConfirmRequest(
                user_id='user-1',
                thread_id='thread-update',
                action_id=pending.pending_action.id,
                action='approve',
            )
        )

        assert completed.task is not None
        assert completed.task.title == '完成最终实验'
        assert completed.task.user_priority == TaskPriority.URGENT
        assert completed.task.effective_priority == TaskPriority.URGENT
        assert completed.task.deadline is not None
        assert completed.task.deadline.isoformat() == '2026-08-14T23:59:59+08:00'
        assert completed.task.version == 2
        assert parser.calls == [
            (
                '把论文任务改名并调整截止时间和优先级',
                'paper',
                'Asia/Shanghai',
            )
        ]
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_attribute_update_clarification_does_not_write() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='attribute:clarify')
    parser = FixedUpdateParser(
        TaskUpdateParseResult(
            changes=[],
            needs_clarification=True,
            clarification_question='你希望将截止时间改到哪一天？',
            reason='缺少新的截止时间',
        )
    )
    task = Task(id='paper', user_id='user-1', title='论文任务')
    try:
        await repository.create(task, idempotency_key='seed-paper')
        graph = build_task_graph(
            GraphDependencies(
                parser=UnusedCreateParser(),
                task_update_parser=parser,
                intent_service=update_intent_service('论文任务'),
                task_repository=repository,
                clock=lambda: NOW,
            ),
            checkpointer=InMemorySaver(),
        )
        response = await TaskAgentService(graph).chat(
            AgentChatRequest(
                user_id='user-1',
                thread_id='thread-clarify',
                request_id='request-clarify',
                message='修改论文任务的截止时间',
                timezone='Asia/Shanghai',
            )
        )
        stored = await repository.get(user_id='user-1', task_id='paper')

        assert response.status == 'needs_clarification'
        assert response.message == '你希望将截止时间改到哪一天？'
        assert response.pending_action is None
        assert stored is not None and stored.version == 1
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_attribute_update_keeps_original_message_after_candidate_selection() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='attribute:selection')
    parser = FixedUpdateParser(
        TaskUpdateParseResult(
            changes=[
                TaskFieldChange(
                    field=TaskFieldName.TITLE,
                    operation=TaskFieldOperation.SET,
                    value='选中的新标题',
                )
            ],
            reason='修改标题',
        )
    )
    try:
        for task_id in ('paper-1', 'paper-2'):
            await repository.create(
                Task(id=task_id, user_id='user-1', title='论文任务'),
                idempotency_key=f'seed-{task_id}',
            )
        graph = build_task_graph(
            GraphDependencies(
                parser=UnusedCreateParser(),
                task_update_parser=parser,
                intent_service=update_intent_service('论文任务'),
                task_repository=repository,
                clock=lambda: NOW,
            ),
            checkpointer=InMemorySaver(),
        )
        service = TaskAgentService(graph)
        first = await service.chat(
            AgentChatRequest(
                user_id='user-1',
                thread_id='thread-selection',
                request_id='request-selection-1',
                message='把论文任务改名为选中的新标题',
                timezone='Asia/Shanghai',
            )
        )
        selected = await service.chat(
            AgentChatRequest(
                user_id='user-1',
                thread_id='thread-selection',
                request_id='request-selection-2',
                message='第一个',
                timezone='Asia/Shanghai',
            )
        )

        assert first.status == 'needs_disambiguation'
        assert selected.status == 'awaiting_confirmation'
        assert parser.calls == [
            ('把论文任务改名为选中的新标题', 'paper-1', 'Asia/Shanghai')
        ]
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_repository_update_is_idempotent_and_versioned() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='attribute:repository')
    task = Task(id='task-1', user_id='user-1', title='旧标题')
    update = TaskUpdate(
        user_id='user-1',
        expected_version=1,
        title='新标题',
    )
    try:
        await repository.create(task, idempotency_key='seed-task')
        first = await repository.update(
            user_id='user-1',
            task_id='task-1',
            update=update,
            idempotency_key='update-1',
        )
        replay = await repository.update(
            user_id='user-1',
            task_id='task-1',
            update=update,
            idempotency_key='update-1',
        )

        assert first == replay
        assert first.title == '新标题'
        assert first.version == 2
    finally:
        await redis.aclose()
