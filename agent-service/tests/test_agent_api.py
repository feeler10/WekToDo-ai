from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import Settings
from app.graph.builder import GraphDependencies, build_task_graph
from app.main import create_app
from app.services.agent import TaskAgentService
from tests.test_human_in_the_loop import (
    InMemoryTaskRepository,
    SequenceParser,
    _draft,
)


def _client() -> tuple[TestClient, InMemoryTaskRepository]:
    repository = InMemoryTaskRepository()
    graph = build_task_graph(
        GraphDependencies(
            parser=SequenceParser(_draft('API 创建任务')),
            task_repository=repository,
        ),
        checkpointer=InMemorySaver(),
    )
    app = create_app(
        Settings(app_env='test'),
        agent_service=TaskAgentService(graph),
    )
    return TestClient(app), repository


def test_chat_confirm_and_repeated_confirm_are_idempotent() -> None:
    client, repository = _client()
    with client:
        chat = client.post(
            '/api/agent/chat',
            json={
                'user_id': 'user-1',
                'thread_id': 'thread-1',
                'request_id': 'request-1',
                'message': '创建一个 API 测试任务',
                'timezone': 'Asia/Shanghai',
            },
        )
        assert chat.status_code == 200
        pending = chat.json()
        assert pending['status'] == 'awaiting_confirmation'
        assert pending['task_draft']['title'] == 'API 创建任务'
        action_id = pending['pending_action']['id']

        confirm_payload = {
            'user_id': 'user-1',
            'thread_id': 'thread-1',
            'action_id': action_id,
            'action': 'approve',
        }
        approved = client.post('/api/agent/confirm', json=confirm_payload)
        replayed = client.post('/api/agent/confirm', json=confirm_payload)
        queried = client.post(
            '/api/agent/chat',
            json={
                'user_id': 'user-1',
                'thread_id': 'thread-query',
                'request_id': 'request-query',
                'message': '查询我的任务',
                'timezone': 'Asia/Shanghai',
            },
        )

    assert approved.status_code == 200
    assert approved.json()['status'] == 'completed'
    assert approved.json()['task']['title'] == 'API 创建任务'
    assert replayed.status_code == 200
    assert replayed.json()['task']['id'] == approved.json()['task']['id']
    assert queried.status_code == 200
    assert queried.json()['tasks'][0]['id'] == approved.json()['task']['id']
    assert repository.create_calls == 1


def test_confirm_cannot_access_another_users_thread() -> None:
    client, _repository = _client()
    with client:
        chat = client.post(
            '/api/agent/chat',
            json={
                'user_id': 'user-a',
                'thread_id': 'shared-name',
                'request_id': 'request-a',
                'message': '创建任务',
            },
        )
        action_id = chat.json()['pending_action']['id']
        response = client.post(
            '/api/agent/confirm',
            json={
                'user_id': 'user-b',
                'thread_id': 'shared-name',
                'action_id': action_id,
                'action': 'approve',
            },
        )

    assert response.status_code == 404
    assert response.json()['error']['code'] == 'thread_not_found'
