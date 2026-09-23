import json
from typing import Any
from urllib.parse import quote

from redis.asyncio import Redis

from app.repositories.exceptions import (
    ObservabilityRepositoryConsistencyError,
)
from app.repositories.observability import ObservabilityRepository
from app.schemas.audit import ToolExecutionLog
from app.schemas.trace import TraceEvent, TraceRecord


class RedisObservabilityRepository(ObservabilityRepository):
    def __init__(
        self,
        redis: Redis,
        *,
        tool_log_ttl_seconds: int = 2_592_000,
        trace_ttl_seconds: int = 604_800,
        trace_max_events: int = 1000,
        key_prefix: str = 'wek:observability',
    ) -> None:
        self._redis = redis
        self._tool_log_ttl_seconds = tool_log_ttl_seconds
        self._trace_ttl_seconds = trace_ttl_seconds
        self._trace_max_events = trace_max_events
        self._key_prefix = key_prefix

    async def start_trace(self, trace: TraceRecord) -> None:
        key = self._trace_key(trace.tenant_id, trace.user_id, trace.trace_id)
        created = await self._redis.set(
            key,
            self._dump(trace),
            ex=self._trace_ttl_seconds,
            nx=True,
        )
        if not created:
            raise ObservabilityRepositoryConsistencyError(
                'Trace ID already exists'
            )
        index = self._user_trace_index(trace.tenant_id, trace.user_id)
        pipeline = self._redis.pipeline(transaction=True)
        pipeline.zadd(index, {trace.trace_id: trace.started_at.timestamp()})
        pipeline.expire(index, self._trace_ttl_seconds)
        await pipeline.execute()

    async def finish_trace(self, trace: TraceRecord) -> None:
        key = self._trace_key(trace.tenant_id, trace.user_id, trace.trace_id)
        updated = await self._redis.set(
            key,
            self._dump(trace),
            ex=self._trace_ttl_seconds,
            xx=True,
        )
        if not updated:
            raise ObservabilityRepositoryConsistencyError(
                'Trace record does not exist'
            )

    async def append_trace_event(self, event: TraceEvent) -> None:
        key = self._trace_events_key(
            event.tenant_id,
            event.user_id,
            event.trace_id,
        )
        payload = self._dump(event)
        pipeline = self._redis.pipeline(transaction=True)
        pipeline.zadd(key, {payload: float(event.sequence)})
        pipeline.zremrangebyrank(key, 0, -self._trace_max_events - 1)
        pipeline.expire(key, self._trace_ttl_seconds)
        await pipeline.execute()

    async def start_tool_execution(self, log: ToolExecutionLog) -> None:
        key = self._tool_key(
            log.tenant_id,
            log.user_id,
            log.tool_call_id,
        )
        created = await self._redis.set(
            key,
            self._dump(log),
            ex=self._tool_log_ttl_seconds,
            nx=True,
        )
        if not created:
            raise ObservabilityRepositoryConsistencyError(
                'Tool call ID already exists'
            )
        index = self._trace_tools_key(
            log.tenant_id,
            log.user_id,
            log.trace_id,
        )
        pipeline = self._redis.pipeline(transaction=True)
        pipeline.zadd(index, {log.tool_call_id: log.started_at.timestamp()})
        pipeline.expire(index, self._tool_log_ttl_seconds)
        await pipeline.execute()

    async def finish_tool_execution(self, log: ToolExecutionLog) -> None:
        key = self._tool_key(
            log.tenant_id,
            log.user_id,
            log.tool_call_id,
        )
        updated = await self._redis.set(
            key,
            self._dump(log),
            ex=self._tool_log_ttl_seconds,
            xx=True,
        )
        if not updated:
            raise ObservabilityRepositoryConsistencyError(
                'Tool execution record does not exist'
            )

    async def get_trace(
        self,
        *,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> TraceRecord | None:
        payload = await self._redis.get(
            self._trace_key(tenant_id, user_id, trace_id)
        )
        return TraceRecord.model_validate_json(payload) if payload else None

    async def list_trace_events(
        self,
        *,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> list[TraceEvent]:
        payloads = await self._redis.zrange(
            self._trace_events_key(tenant_id, user_id, trace_id),
            0,
            -1,
        )
        return [TraceEvent.model_validate_json(payload) for payload in payloads]

    async def list_tool_executions(
        self,
        *,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> list[ToolExecutionLog]:
        tool_call_ids = await self._redis.zrange(
            self._trace_tools_key(tenant_id, user_id, trace_id),
            0,
            -1,
        )
        if not tool_call_ids:
            return []
        keys = [
            self._tool_key(tenant_id, user_id, self._text(tool_call_id))
            for tool_call_id in tool_call_ids
        ]
        payloads = await self._redis.mget(keys)
        return [
            ToolExecutionLog.model_validate_json(payload)
            for payload in payloads
            if payload is not None
        ]

    @staticmethod
    def _dump(model: Any) -> str:
        return json.dumps(
            model.model_dump(mode='json'),
            ensure_ascii=False,
            separators=(',', ':'),
        )

    @staticmethod
    def _text(value: Any) -> str:
        return value.decode('utf-8') if isinstance(value, bytes) else str(value)

    def _scope(self, tenant_id: str, user_id: str) -> str:
        return ':'.join(
            (
                self._key_prefix,
                quote(tenant_id, safe=''),
                quote(user_id, safe=''),
            )
        )

    def _trace_key(self, tenant_id: str, user_id: str, trace_id: str) -> str:
        return f'{self._scope(tenant_id, user_id)}:trace:{quote(trace_id, safe="")}'

    def _trace_events_key(
        self,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> str:
        return f'{self._trace_key(tenant_id, user_id, trace_id)}:events'

    def _tool_key(self, tenant_id: str, user_id: str, tool_call_id: str) -> str:
        return f'{self._scope(tenant_id, user_id)}:tool:{quote(tool_call_id, safe="")}'

    def _trace_tools_key(
        self,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> str:
        return f'{self._trace_key(tenant_id, user_id, trace_id)}:tools'

    def _user_trace_index(self, tenant_id: str, user_id: str) -> str:
        return f'{self._scope(tenant_id, user_id)}:traces'
