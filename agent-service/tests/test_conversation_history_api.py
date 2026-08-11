from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from app.core.config import Settings
from app.graph.builder import GraphDependencies, build_task_graph
from app.main import create_app
from app.repositories.conversation import ConversationRepository
from app.repositories.redis_conversation import RedisConversationRepository
from app.schemas.agent import AgentChatRequest, AgentResponse
from app.schemas.conversation import (
    ConversationHistoryResponse,
    ConversationScope,
)
from app.services.agent import TaskAgentService
from tests.intent_helpers import existing_flow_intent_service
from tests.test_human_in_the_loop import (
    InMemoryTaskRepository,
    SequenceParser,
    _draft,
)


class FailingConversationRepository(ConversationRepository):
    async def append_exchange(
        self,
        *,
        scope: ConversationScope,
        operation_id: str,
        user_content: str,
        assistant_response: AgentResponse,
    ) -> None:
        raise RuntimeError('history unavailable')

    async def get_history(
        self,
        *,
        scope: ConversationScope,
    ) -> ConversationHistoryResponse:
        return ConversationHistoryResponse(**scope.model_dump())


@pytest.mark.anyio
async def test_history_api_restores_messages_and_pending_confirmation() -> None:
    redis = FakeRedis(decode_responses=True)
    conversation_repository = RedisConversationRepository(
        redis,
        key_prefix='history-api',
    )
    graph = build_task_graph(
        GraphDependencies(
            intent_service=existing_flow_intent_service(),
            parser=SequenceParser(
                {
                    'title': None,
                    'missing_fields': ['title'],
                    'clarification_question': '这个任务叫什么？',
                },
                _draft('刷新后恢复的任务'),
            ),
            task_repository=InMemoryTaskRepository(),
        ),
        checkpointer=InMemorySaver(),
    )
    service = TaskAgentService(
        graph,
        conversation_repository=conversation_repository,
    )
    app = create_app(
        Settings(app_env='test'),
        redis_client=redis,
        agent_service=service,
    )
    transport = ASGITransport(app=app)
    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=transport,
                base_url='http://testserver',
            ) as client:
                first = await client.post(
                    '/api/agent/chat',
                    json={
                        'user_id': 'user-1',
                        'thread_id': 'conversation-1',
                        'request_id': 'request-1',
                        'message': '创建一个任务',
                        'timezone': 'Asia/Shanghai',
                    },
                )
                after_first = await client.get(
                    '/api/agent/conversations/conversation-1',
                    params={'user_id': 'user-1'},
                )
                second = await client.post(
                    '/api/agent/chat',
                    json={
                        'user_id': 'user-1',
                        'thread_id': 'conversation-1',
                        'request_id': 'request-2',
                        'message': '标题叫刷新后恢复的任务',
                        'timezone': 'Asia/Shanghai',
                    },
                )
                restored = await client.get(
                    '/api/agent/conversations/conversation-1',
                    params={'user_id': 'user-1'},
                )
                other_user = await client.get(
                    '/api/agent/conversations/conversation-1',
                    params={'user_id': 'user-2'},
                )

                assert first.json()['status'] == 'needs_clarification'
                assert after_first.status_code == 200
                assert len(after_first.json()['messages']) == 2
                assert second.json()['status'] == 'awaiting_confirmation'
                assert [
                    item['content'] for item in restored.json()['messages']
                ] == [
                    '创建一个任务',
                    '这个任务叫什么？',
                    '标题叫刷新后恢复的任务',
                    second.json()['message'],
                ]
                last_response = restored.json()['messages'][-1]['response']
                assert last_response['status'] == 'awaiting_confirmation'
                assert last_response['pending_action']['id'] == (
                    second.json()['pending_action']['id']
                )
                assert other_user.json()['messages'] == []
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_repeated_confirmation_is_not_duplicated_in_history() -> None:
    redis = FakeRedis(decode_responses=True)
    conversation_repository = RedisConversationRepository(
        redis,
        key_prefix='history-confirm',
    )
    graph = build_task_graph(
        GraphDependencies(
            intent_service=existing_flow_intent_service(),
            parser=SequenceParser(_draft('确认历史任务')),
            task_repository=InMemoryTaskRepository(),
        ),
        checkpointer=InMemorySaver(),
    )
    app = create_app(
        Settings(app_env='test'),
        redis_client=redis,
        agent_service=TaskAgentService(
            graph,
            conversation_repository=conversation_repository,
        ),
    )
    transport = ASGITransport(app=app)
    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=transport,
                base_url='http://testserver',
            ) as client:
                pending = await client.post(
                    '/api/agent/chat',
                    json={
                        'user_id': 'user-1',
                        'thread_id': 'conversation-confirm',
                        'request_id': 'request-confirm',
                        'message': '创建确认历史任务',
                        'timezone': 'Asia/Shanghai',
                    },
                )
                payload = {
                    'user_id': 'user-1',
                    'thread_id': 'conversation-confirm',
                    'action_id': pending.json()['pending_action']['id'],
                    'action': 'approve',
                }
                approved = await client.post('/api/agent/confirm', json=payload)
                replayed = await client.post('/api/agent/confirm', json=payload)
                history = await client.get(
                    '/api/agent/conversations/conversation-confirm',
                    params={'user_id': 'user-1'},
                )

                assert approved.status_code == 200
                assert replayed.status_code == 200
                assert len(history.json()['messages']) == 4
                assert history.json()['messages'][-2]['content'] == '确认执行'
                assert history.json()['conversation']['message_count'] == 4
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_history_failure_does_not_mask_successful_agent_response(
    caplog,
) -> None:
    graph = build_task_graph(
        GraphDependencies(
            intent_service=existing_flow_intent_service(),
            parser=SequenceParser(_draft('历史写入失败任务')),
            task_repository=InMemoryTaskRepository(),
        ),
        checkpointer=InMemorySaver(),
    )
    service = TaskAgentService(
        graph,
        conversation_repository=FailingConversationRepository(),
    )

    with caplog.at_level('ERROR', logger='app.services.agent'):
        response = await service.chat(
            AgentChatRequest(
                user_id='user-1',
                thread_id='conversation-failure',
                request_id='request-failure',
                message='创建历史写入失败任务',
                timezone='Asia/Shanghai',
            )
        )

    assert response.status == 'awaiting_confirmation'
    assert 'conversation_history_write_failed' in caplog.messages[-1]
