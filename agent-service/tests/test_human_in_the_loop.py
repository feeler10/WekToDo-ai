from collections.abc import Mapping
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.graph.builder import GraphDependencies, build_task_graph
from tests.intent_helpers import existing_flow_intent_service
from app.schemas.task import Task, TaskListResponse, TaskQuery, TaskStatus


class SequenceParser:
    def __init__(self, *results: Mapping[str, Any]) -> None:
        self._results = list(results)
        self.calls: list[str] = []

    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        self.calls.append(user_message)
        return self._results.pop(0)


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.idempotency: dict[str, str] = {}
        self.create_calls = 0

    async def create(self, task: Task, *, idempotency_key: str) -> Task:
        self.create_calls += 1
        existing_id = self.idempotency.get(idempotency_key)
        if existing_id:
            return self.tasks[existing_id]
        self.tasks[task.id] = task
        self.idempotency[idempotency_key] = task.id
        return task

    async def get(self, *, user_id: str, task_id: str) -> Task | None:
        task = self.tasks.get(task_id)
        return task if task and task.user_id == user_id else None

    async def list_tasks(self, query: TaskQuery) -> TaskListResponse:
        tasks = [task for task in self.tasks.values() if task.user_id == query.user_id]
        return TaskListResponse(items=tasks, total=len(tasks))

    async def update_status(
        self,
        *,
        user_id: str,
        task_id: str,
        target_status: TaskStatus,
        expected_version: int,
        confirmed_reopen: bool = False,
    ) -> Task:
        raise NotImplementedError


def _state(thread_id: str) -> dict[str, object]:
    return {
        'user_id': 'user-1',
        'thread_id': thread_id,
        'request_id': f'request-{thread_id}',
        'user_message': '创建论文提交任务',
        'timezone': 'Asia/Shanghai',
    }


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    return {'configurable': {'thread_id': thread_id}}


def _draft(title: str) -> dict[str, object]:
    return {
        'title': title,
        'deadline_score': 80,
        'semantic_importance': 80,
        'impact_score': 50,
        'workload_risk_score': 20,
        'dependency_score': 10,
    }


def _action_id(result: dict[str, Any]) -> str:
    return result['__interrupt__'][0].value['pending_action']['id']


@pytest.mark.anyio
async def test_approve_resumes_checkpoint_and_creates_once() -> None:
    repository = InMemoryTaskRepository()
    graph = build_task_graph(
        GraphDependencies(
            intent_service=existing_flow_intent_service(),
            parser=SequenceParser(_draft('提交论文')),
            task_repository=repository,
        ),
        checkpointer=InMemorySaver(),
    )
    config = _config('approve-thread')

    interrupted = await graph.ainvoke(_state('approve-thread'), config=config)
    assert repository.create_calls == 0

    completed = await graph.ainvoke(
        Command(
            resume={
                'action_id': _action_id(interrupted),
                'action': 'approve',
            }
        ),
        config=config,
    )

    assert completed['created_task']['title'] == '提交论文'
    assert completed['confirmation_status'] == 'approved'
    assert repository.create_calls == 1


@pytest.mark.anyio
async def test_edit_returns_to_validation_and_requires_new_confirmation() -> None:
    repository = InMemoryTaskRepository()
    graph = build_task_graph(
        GraphDependencies(
            intent_service=existing_flow_intent_service(),
            parser=SequenceParser(_draft('旧标题')),
            task_repository=repository,
        ),
        checkpointer=InMemorySaver(),
    )
    config = _config('edit-thread')
    first = await graph.ainvoke(_state('edit-thread'), config=config)

    edited = await graph.ainvoke(
        Command(
            resume={
                'action_id': _action_id(first),
                'action': 'edit',
                'edits': {'title': '新标题', 'user_priority': 'URGENT'},
            }
        ),
        config=config,
    )

    assert edited['task_draft']['title'] == '新标题'
    assert edited['user_priority'] == 'URGENT'
    assert _action_id(edited) != _action_id(first)
    assert repository.create_calls == 0

    completed = await graph.ainvoke(
        Command(
            resume={'action_id': _action_id(edited), 'action': 'approve'}
        ),
        config=config,
    )
    assert completed['created_task']['title'] == '新标题'
    assert completed['created_task']['user_priority'] == 'URGENT'


@pytest.mark.anyio
async def test_reject_ends_without_writing() -> None:
    repository = InMemoryTaskRepository()
    graph = build_task_graph(
        GraphDependencies(
            intent_service=existing_flow_intent_service(),
            parser=SequenceParser(_draft('不要创建')),
            task_repository=repository,
        ),
        checkpointer=InMemorySaver(),
    )
    config = _config('reject-thread')
    first = await graph.ainvoke(_state('reject-thread'), config=config)

    rejected = await graph.ainvoke(
        Command(
            resume={'action_id': _action_id(first), 'action': 'reject'}
        ),
        config=config,
    )

    assert rejected['final_response'] == 'Task creation rejected'
    assert rejected['confirmation_status'] == 'rejected'
    assert repository.create_calls == 0


@pytest.mark.anyio
async def test_regenerate_parses_again_and_interrupts_with_new_draft() -> None:
    parser = SequenceParser(_draft('第一版'), _draft('重新生成版'))
    repository = InMemoryTaskRepository()
    graph = build_task_graph(
        GraphDependencies(intent_service=existing_flow_intent_service(), parser=parser, task_repository=repository),
        checkpointer=InMemorySaver(),
    )
    config = _config('regenerate-thread')
    first = await graph.ainvoke(_state('regenerate-thread'), config=config)

    regenerated = await graph.ainvoke(
        Command(
            resume={
                'action_id': _action_id(first),
                'action': 'regenerate',
                'feedback': '标题更明确',
            }
        ),
        config=config,
    )

    assert regenerated['task_draft']['title'] == '重新生成版'
    assert len(parser.calls) == 2
    assert 'Regeneration feedback: 标题更明确' in parser.calls[1]
    assert _action_id(regenerated) != _action_id(first)
    assert repository.create_calls == 0
