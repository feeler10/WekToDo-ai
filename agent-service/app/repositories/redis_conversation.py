from collections.abc import Callable
from datetime import datetime
from typing import Literal
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from redis.asyncio import Redis
from redis.exceptions import WatchError

from app.repositories.conversation import ConversationRepository
from app.repositories.exceptions import (
    ConversationRepositoryConcurrencyError,
    ConversationRepositoryConsistencyError,
)
from app.schemas.agent import AgentResponse
from app.schemas.conversation import (
    ConversationHistoryResponse,
    ConversationMessage,
    ConversationRecord,
    ConversationScope,
)
from app.schemas.task import utc_now


class RedisConversationRepository(ConversationRepository):
    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = 'wektodo',
        max_messages: int = 200,
        idempotency_ttl_seconds: int = 604800,
        transaction_retries: int = 3,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if max_messages < 2:
            raise ValueError('max_messages must be at least 2')
        if max_messages % 2:
            raise ValueError('max_messages must preserve complete exchanges')
        if idempotency_ttl_seconds < 60:
            raise ValueError('idempotency_ttl_seconds must be at least 60')
        if transaction_retries < 1:
            raise ValueError('transaction_retries must be at least 1')
        self._redis = redis
        self._key_prefix = key_prefix.strip(':')
        self._max_messages = max_messages
        self._idempotency_ttl_seconds = idempotency_ttl_seconds
        self._transaction_retries = transaction_retries
        self._clock = clock

    async def append_exchange(
        self,
        *,
        scope: ConversationScope,
        operation_id: str,
        user_content: str,
        assistant_response: AgentResponse,
    ) -> None:
        if not operation_id:
            raise ValueError('operation_id must not be empty')
        if assistant_response.thread_id != scope.conversation_id:
            raise ValueError('assistant response belongs to another conversation')
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('clock must return a timezone-aware datetime')
        conversation_key = self._conversation_key(scope)
        messages_key = self._messages_key(scope)
        operation_key = self._operation_key(scope, operation_id)
        index_key = self._conversation_index_key(scope)

        for _attempt in range(self._transaction_retries):
            try:
                async with self._redis.pipeline(transaction=True) as pipeline:
                    await pipeline.watch(operation_key, conversation_key)
                    if await pipeline.exists(operation_key):
                        await pipeline.unwatch()
                        return
                    stored = await pipeline.get(conversation_key)
                    existing = (
                        ConversationRecord.model_validate_json(stored)
                        if stored is not None
                        else None
                    )
                    self._validate_scope(existing, scope)
                    conversation = ConversationRecord(
                        **scope.model_dump(),
                        title=(
                            existing.title
                            if existing is not None
                            else self._title_from(user_content)
                        ),
                        created_at=(existing.created_at if existing else now),
                        updated_at=now,
                        message_count=(
                            (existing.message_count if existing else 0) + 2
                        ),
                    )
                    user_message = self._message(
                        scope=scope,
                        operation_id=operation_id,
                        role='user',
                        content=user_content,
                        response=None,
                        created_at=now,
                    )
                    assistant_message = self._message(
                        scope=scope,
                        operation_id=operation_id,
                        role='assistant',
                        content=assistant_response.message,
                        response=assistant_response,
                        created_at=now,
                    )
                    pipeline.multi()
                    pipeline.rpush(
                        messages_key,
                        user_message.model_dump_json(),
                        assistant_message.model_dump_json(),
                    )
                    pipeline.ltrim(messages_key, -self._max_messages, -1)
                    pipeline.set(
                        conversation_key,
                        conversation.model_dump_json(),
                    )
                    pipeline.zadd(
                        index_key,
                        {scope.conversation_id: now.timestamp()},
                    )
                    pipeline.set(
                        operation_key,
                        '1',
                        ex=self._idempotency_ttl_seconds,
                    )
                    await pipeline.execute()
                    return
            except WatchError:
                continue

        raise ConversationRepositoryConcurrencyError(
            'Could not append conversation history after concurrent updates'
        )

    async def get_history(
        self,
        *,
        scope: ConversationScope,
    ) -> ConversationHistoryResponse:
        async with self._redis.pipeline(transaction=False) as pipeline:
            pipeline.get(self._conversation_key(scope))
            pipeline.lrange(self._messages_key(scope), 0, -1)
            conversation_payload, message_payloads = await pipeline.execute()
        conversation = (
            ConversationRecord.model_validate_json(conversation_payload)
            if conversation_payload is not None
            else None
        )
        self._validate_scope(conversation, scope)
        messages = [
            ConversationMessage.model_validate_json(payload)
            for payload in message_payloads
        ]
        for message in messages:
            self._validate_scope(message, scope)
        if conversation is None and messages:
            raise ConversationRepositoryConsistencyError(
                'Conversation messages exist without metadata'
            )
        return ConversationHistoryResponse(
            **scope.model_dump(),
            conversation=conversation,
            messages=messages,
        )

    def _message(
        self,
        *,
        scope: ConversationScope,
        operation_id: str,
        role: Literal['user', 'assistant'],
        content: str,
        response: AgentResponse | None,
        created_at: datetime,
    ) -> ConversationMessage:
        message_id = str(
            uuid5(
                NAMESPACE_URL,
                ':'.join(
                    (
                        scope.tenant_id,
                        scope.user_id,
                        scope.conversation_id,
                        operation_id,
                        role,
                    )
                ),
            )
        )
        return ConversationMessage(
            **scope.model_dump(),
            id=message_id,
            role=role,
            content=content,
            operation_id=operation_id,
            created_at=created_at,
            response=response,
        )

    @staticmethod
    def _title_from(content: str) -> str:
        title = ' '.join(content.split())[:100]
        return title or '新对话'

    @staticmethod
    def _validate_scope(
        value: ConversationScope | None,
        expected: ConversationScope,
    ) -> None:
        if value is None:
            return
        if (
            value.tenant_id != expected.tenant_id
            or value.user_id != expected.user_id
            or value.conversation_id != expected.conversation_id
        ):
            raise ConversationRepositoryConsistencyError(
                'Stored conversation has invalid ownership'
            )

    def _conversation_key(self, scope: ConversationScope) -> str:
        return f'{self._scope_prefix(scope)}:metadata'

    def _messages_key(self, scope: ConversationScope) -> str:
        return f'{self._scope_prefix(scope)}:messages'

    def _operation_key(
        self,
        scope: ConversationScope,
        operation_id: str,
    ) -> str:
        return (
            f'{self._scope_prefix(scope)}:operation:'
            f'{quote(operation_id, safe="")}'
        )

    def _conversation_index_key(self, scope: ConversationScope) -> str:
        return ':'.join(
            (
                self._key_prefix,
                'conversation_index',
                quote(scope.tenant_id, safe=''),
                quote(scope.user_id, safe=''),
            )
        )

    def _scope_prefix(self, scope: ConversationScope) -> str:
        return ':'.join(
            (
                self._key_prefix,
                'conversation',
                quote(scope.tenant_id, safe=''),
                quote(scope.user_id, safe=''),
                quote(scope.conversation_id, safe=''),
            )
        )
