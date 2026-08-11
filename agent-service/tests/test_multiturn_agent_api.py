from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import Settings
from app.graph.builder import GraphDependencies, build_task_graph
from app.intent.enums import IntentType
from app.intent.models import IntentResult
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.main import create_app
from app.schemas.task import Task
from app.services.agent import TaskAgentService
from tests.test_human_in_the_loop import InMemoryTaskRepository
from tests.test_task_update_clarification import (
    SequenceUpdateParser,
    UnusedCreateParser,
    clarification,
    title_change,
)


def test_update_collects_three_turns_via_api_and_writes_only_after_confirm() -> None:
    repository = InMemoryTaskRepository()
    repository.tasks['water'] = Task(
        id='water',
        user_id='user-1',
        title='接水任务',
    )
    parser = SequenceUpdateParser(
        [
            clarification('请问您想修改接水任务的哪些内容？'),
            clarification('您想把标题修改成什么？'),
            title_change('每天早上接水'),
        ]
    )
    intent_service = IntentRecognitionService(
        FakeIntentClassifier(
            result=IntentResult(
                intent=IntentType.UPDATE_TASK,
                confidence=1,
                reason='修改接水任务',
                task_reference='接水任务',
            )
        )
    )
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedCreateParser(),
            task_update_parser=parser,
            intent_service=intent_service,
            task_repository=repository,
        ),
        checkpointer=InMemorySaver(),
    )
    app = create_app(
        Settings(app_env='test'),
        agent_service=TaskAgentService(graph),
    )
    messages = ['修改接水任务', '标题', '改成每天早上接水']

    with TestClient(app) as client:
        responses = []
        for number, message in enumerate(messages, start=1):
            response = client.post(
                '/api/agent/chat',
                json={
                    'user_id': 'user-1',
                    'thread_id': 'update-thread',
                    'request_id': f'update-request-{number}',
                    'message': message,
                    'timezone': 'Asia/Shanghai',
                },
            )
            assert response.status_code == 200
            responses.append(response.json())
            stored = repository.tasks['water']
            assert stored.title == '接水任务'
            assert stored.version == 1

        assert [response['status'] for response in responses] == [
            'needs_clarification',
            'needs_clarification',
            'awaiting_confirmation',
        ]
        action_id = responses[-1]['pending_action']['id']
        confirmed = client.post(
            '/api/agent/confirm',
            json={
                'user_id': 'user-1',
                'thread_id': 'update-thread',
                'action_id': action_id,
                'action': 'approve',
            },
        )

    assert confirmed.status_code == 200
    assert confirmed.json()['status'] == 'completed'
    assert confirmed.json()['task']['title'] == '每天早上接水'
    assert confirmed.json()['task']['version'] == 2
    assert repository.tasks['water'].title == '每天早上接水'
    assert '[第1轮] 修改接水任务' in parser.calls[-1][0]
    assert '[第2轮] 标题' in parser.calls[-1][0]
    assert '[第3轮] 改成每天早上接水' in parser.calls[-1][0]
