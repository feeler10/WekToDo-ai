import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.repositories.redis_observability import RedisObservabilityRepository
from app.schemas.trace import TraceEvent, TraceEventType, TraceRecord


REDIS_URL = os.getenv('TEST_REDIS_URL', 'redis://[::1]:6379/15')


@pytest.mark.integration
@pytest.mark.anyio
async def test_trace_survives_observability_repository_rebuild() -> None:
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    key_prefix = f'wektodo:observability-test:{uuid4().hex}'
    trace = TraceRecord(
        trace_id='persistent-trace',
        tenant_id='default',
        user_id='integration-user',
        thread_id='integration-thread',
        request_id='integration-request',
        operation='chat',
    )
    try:
        assert await redis.ping()
        first = RedisObservabilityRepository(redis, key_prefix=key_prefix)
        await first.start_trace(trace)
        await first.append_trace_event(
            TraceEvent(
                event_id='persistent-event',
                trace_id=trace.trace_id,
                tenant_id=trace.tenant_id,
                user_id=trace.user_id,
                thread_id=trace.thread_id,
                sequence=1,
                event_type=TraceEventType.REQUEST_STARTED,
            )
        )

        rebuilt = RedisObservabilityRepository(redis, key_prefix=key_prefix)
        restored = await rebuilt.get_trace(
            tenant_id='default',
            user_id='integration-user',
            trace_id=trace.trace_id,
        )
        events = await rebuilt.list_trace_events(
            tenant_id='default',
            user_id='integration-user',
            trace_id=trace.trace_id,
        )

        assert restored == trace
        assert [item.event_id for item in events] == ['persistent-event']
    finally:
        keys = [key async for key in redis.scan_iter(match=f'{key_prefix}:*')]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
