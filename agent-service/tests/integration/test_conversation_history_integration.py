import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.repositories.redis_conversation import RedisConversationRepository
from app.schemas.agent import AgentResponse
from app.schemas.conversation import ConversationScope


REDIS_URL = os.getenv('TEST_REDIS_URL', 'redis://[::1]:6379/15')


@pytest.mark.integration
@pytest.mark.anyio
async def test_conversation_history_survives_repository_rebuild() -> None:
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    key_prefix = f'wektodo:conversation-test:{uuid4().hex}'
    scope = ConversationScope(
        tenant_id='default',
        user_id='integration-user',
        conversation_id='persistent-conversation',
    )
    try:
        assert await redis.ping()
        first_repository = RedisConversationRepository(
            redis,
            key_prefix=key_prefix,
        )
        await first_repository.append_exchange(
            scope=scope,
            operation_id='chat:integration-request',
            user_content='需要跨刷新恢复的消息',
            assistant_response=AgentResponse(
                status='needs_clarification',
                thread_id=scope.conversation_id,
                message='请继续补充。',
            ),
        )

        rebuilt_repository = RedisConversationRepository(
            redis,
            key_prefix=key_prefix,
        )
        restored = await rebuilt_repository.get_history(scope=scope)

        assert restored.conversation is not None
        assert restored.conversation.message_count == 2
        assert [message.content for message in restored.messages] == [
            '需要跨刷新恢复的消息',
            '请继续补充。',
        ]
    finally:
        keys = [key async for key in redis.scan_iter(match=f'{key_prefix}:*')]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
