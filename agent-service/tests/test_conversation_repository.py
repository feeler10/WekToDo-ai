from datetime import datetime, timedelta, timezone

import pytest
from fakeredis.aioredis import FakeRedis

from app.repositories.redis_conversation import RedisConversationRepository
from app.schemas.agent import AgentResponse
from app.schemas.conversation import ConversationScope


NOW = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        current = self.now
        self.now += timedelta(seconds=1)
        return current


def response(thread_id: str, message: str) -> AgentResponse:
    return AgentResponse(
        status='completed',
        thread_id=thread_id,
        message=message,
    )


@pytest.mark.anyio
async def test_append_history_is_idempotent_and_bounded() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisConversationRepository(
        redis,
        key_prefix='conversation:test',
        max_messages=4,
        clock=MutableClock(),
    )
    scope = ConversationScope(
        tenant_id='tenant-a',
        user_id='user-1',
        conversation_id='conversation-1',
    )
    try:
        await repository.append_exchange(
            scope=scope,
            operation_id='chat:request-1',
            user_content='第一条消息',
            assistant_response=response('conversation-1', '第一条回复'),
        )
        await repository.append_exchange(
            scope=scope,
            operation_id='chat:request-1',
            user_content='重复请求不应写入',
            assistant_response=response('conversation-1', '重复回复'),
        )
        for number in (2, 3):
            await repository.append_exchange(
                scope=scope,
                operation_id=f'chat:request-{number}',
                user_content=f'第{number}条消息',
                assistant_response=response(
                    'conversation-1',
                    f'第{number}条回复',
                ),
            )

        history = await repository.get_history(scope=scope)

        assert history.conversation is not None
        assert history.conversation.title == '第一条消息'
        assert history.conversation.message_count == 6
        assert [message.content for message in history.messages] == [
            '第2条消息',
            '第2条回复',
            '第3条消息',
            '第3条回复',
        ]
        assert await redis.zscore(
            'conversation:test:conversation_index:tenant-a:user-1',
            'conversation-1',
        ) is not None
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_history_is_isolated_by_tenant_user_and_conversation() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisConversationRepository(
        redis,
        key_prefix='conversation:isolation',
    )
    original = ConversationScope(
        tenant_id='tenant-a',
        user_id='user-1',
        conversation_id='shared-id',
    )
    try:
        await repository.append_exchange(
            scope=original,
            operation_id='chat:request-1',
            user_content='私有消息',
            assistant_response=response('shared-id', '私有回复'),
        )

        scopes = [
            ConversationScope(
                tenant_id='tenant-b',
                user_id='user-1',
                conversation_id='shared-id',
            ),
            ConversationScope(
                tenant_id='tenant-a',
                user_id='user-2',
                conversation_id='shared-id',
            ),
            ConversationScope(
                tenant_id='tenant-a',
                user_id='user-1',
                conversation_id='other-id',
            ),
        ]
        isolated = [
            await repository.get_history(scope=scope) for scope in scopes
        ]

        assert all(item.conversation is None for item in isolated)
        assert all(item.messages == [] for item in isolated)
    finally:
        await redis.aclose()
