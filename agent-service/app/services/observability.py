import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from datetime import date, datetime
from enum import Enum
from functools import wraps
from time import perf_counter
from typing import Any, ParamSpec, TypeVar
from uuid import uuid4

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError

from app.repositories.exceptions import ToolAuditPersistenceError
from app.repositories.observability import ObservabilityRepository
from app.schemas.audit import (
    ToolExecutionLog,
    ToolExecutionStatus,
)
from app.schemas.task import utc_now
from app.schemas.trace import (
    TraceEvent,
    TraceEventType,
    TraceRecord,
    TraceStatus,
)
from app.services.error_mapping import map_exception
from app.services.exceptions import ModelOutputInvalidError, ModelUnavailableError


logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')

_SENSITIVE_KEY_PARTS = (
    'api_key',
    'apikey',
    'authorization',
    'cookie',
    'password',
    'secret',
    'access_token',
    'refresh_token',
)


class _TraceContext:
    def __init__(self, service: 'ObservabilityService', trace: TraceRecord) -> None:
        self.service = service
        self.trace = trace


_CURRENT_TRACE: ContextVar[_TraceContext | None] = ContextVar(
    'current_observability_trace',
    default=None,
)


class ObservabilityService:
    def __init__(
        self,
        repository: ObservabilityRepository | None = None,
        *,
        tenant_id: str = 'default',
    ) -> None:
        self.repository = repository
        self.tenant_id = tenant_id
        self._event_sequences: dict[str, int] = {}

    async def start_trace(
        self,
        *,
        user_id: str,
        thread_id: str,
        request_id: str,
        operation: str,
        parent_trace_id: str | None = None,
        input_payload: Mapping[str, Any] | None = None,
    ) -> TraceRecord:
        trace = TraceRecord(
            trace_id=str(uuid4()),
            parent_trace_id=parent_trace_id,
            tenant_id=self.tenant_id,
            user_id=user_id,
            thread_id=thread_id,
            request_id=request_id,
            operation=operation,
        )
        if self.repository is not None:
            try:
                self._event_sequences[trace.trace_id] = 0
                await self.repository.start_trace(trace)
                await self.record_event(
                    trace=trace,
                    event_type=TraceEventType.REQUEST_STARTED,
                    success=True,
                    metadata={
                        'operation': operation,
                        'input': _detailed_payload(input_payload or {}),
                    },
                )
            except Exception:
                logger.exception(
                    'trace_start_failed trace_id=%s user_id=%s thread_id=%s',
                    trace.trace_id,
                    user_id,
                    thread_id,
                )
        return trace

    async def finish_trace(
        self,
        trace: TraceRecord,
        *,
        status: TraceStatus,
        error_code: str | None = None,
        output_payload: Mapping[str, Any] | BaseModel | None = None,
    ) -> TraceRecord:
        completed_at = utc_now()
        finished = trace.model_copy(
            update={
                'status': status,
                'completed_at': completed_at,
                'duration_ms': max(
                    0,
                    int((completed_at - trace.started_at).total_seconds() * 1000),
                ),
                'error_code': error_code,
            }
        )
        if self.repository is not None:
            try:
                await self.record_event(
                    trace=trace,
                    event_type=(
                        TraceEventType.INTERRUPTED
                        if status == TraceStatus.INTERRUPTED
                        else TraceEventType.REQUEST_COMPLETED
                    ),
                    success=status != TraceStatus.FAILED,
                    error_code=error_code,
                    metadata={
                        'status': status.value,
                        'output': _detailed_payload(output_payload or {}),
                    },
                )
                await self.repository.finish_trace(finished)
            except Exception:
                logger.exception(
                    'trace_finish_failed trace_id=%s status=%s',
                    trace.trace_id,
                    status.value,
                )
            finally:
                self._event_sequences.pop(trace.trace_id, None)
        return finished

    async def record_event(
        self,
        *,
        trace: TraceRecord,
        event_type: TraceEventType,
        node_name: str | None = None,
        started_at: Any | None = None,
        completed_at: Any | None = None,
        duration_ms: int | None = None,
        success: bool | None = None,
        error_code: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if self.repository is None:
            return
        event = TraceEvent(
            event_id=str(uuid4()),
            trace_id=trace.trace_id,
            tenant_id=trace.tenant_id,
            user_id=trace.user_id,
            thread_id=trace.thread_id,
            sequence=self._next_sequence(trace.trace_id),
            event_type=event_type,
            node_name=node_name,
            started_at=started_at or utc_now(),
            completed_at=completed_at,
            duration_ms=duration_ms,
            success=success,
            error_code=error_code,
            metadata=dict(metadata or {}),
        )
        try:
            await self.repository.append_trace_event(event)
        except Exception:
            logger.exception(
                'trace_event_write_failed trace_id=%s event_type=%s node=%s',
                trace.trace_id,
                event_type.value,
                node_name,
            )

    def _next_sequence(self, trace_id: str) -> int:
        sequence = self._event_sequences.get(trace_id, 0) + 1
        self._event_sequences[trace_id] = sequence
        return sequence

    def wrap_graph_node(
        self,
        name: str,
        node: Callable[..., Any],
    ) -> Callable[..., Awaitable[Any]]:
        @wraps(node)
        async def traced(state: Mapping[str, Any], *args: Any, **kwargs: Any) -> Any:
            trace = self._trace_from_state(state)
            started_at = utc_now()
            started = perf_counter()
            context_token = (
                _CURRENT_TRACE.set(_TraceContext(self, trace))
                if trace is not None
                else None
            )
            if trace is not None:
                await self.record_event(
                    trace=trace,
                    event_type=TraceEventType.NODE_STARTED,
                    node_name=name,
                    started_at=started_at,
                    metadata={
                        'input_state': _detailed_payload(state),
                    },
                )
            try:
                result = node(state, *args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:
                if trace is not None:
                    error = map_exception(exc, trace_id=trace.trace_id)
                    await self.record_event(
                        trace=trace,
                        event_type=TraceEventType.NODE_COMPLETED,
                        node_name=name,
                        started_at=started_at,
                        completed_at=utc_now(),
                        duration_ms=int((perf_counter() - started) * 1000),
                        success=False,
                        error_code=error.code,
                        metadata={
                            'exception_type': type(exc).__name__,
                        },
                    )
                raise
            else:
                error_code = None
                success = True
                if isinstance(result, Mapping):
                    raw_error = result.get('error')
                    if isinstance(raw_error, Mapping):
                        error_code = str(raw_error.get('code') or 'workflow_error')
                        success = False
                    elif result.get('error_message'):
                        error_code = 'workflow_error'
                        success = False
                if trace is not None:
                    await self.record_event(
                        trace=trace,
                        event_type=TraceEventType.NODE_COMPLETED,
                        node_name=name,
                        started_at=started_at,
                        completed_at=utc_now(),
                        duration_ms=int((perf_counter() - started) * 1000),
                        success=success,
                        error_code=error_code,
                        metadata={
                            'output_patch': _detailed_payload(result),
                        },
                    )
                return result
            finally:
                if context_token is not None:
                    _CURRENT_TRACE.reset(context_token)

        return traced

    async def execute_tool(
        self,
        *,
        state: Mapping[str, Any],
        tool_name: str,
        input_payload: Mapping[str, Any],
        confirmed: bool,
        idempotency_key: str | None,
        action_id: str | None,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        if self.repository is None:
            return await operation()
        trace = self._trace_from_state(state)
        trace_id = trace.trace_id if trace is not None else str(uuid4())
        started_at = utc_now()
        started = perf_counter()
        tool_call_id = str(uuid4())
        log = ToolExecutionLog(
            id=tool_call_id,
            tenant_id=self.tenant_id,
            user_id=str(state.get('user_id') or ''),
            thread_id=str(state.get('thread_id') or ''),
            request_id=str(state.get('request_id') or state.get('thread_id') or ''),
            trace_id=trace_id,
            tool_call_id=tool_call_id,
            action_id=action_id,
            tool_name=tool_name,
            input_payload=_detailed_payload(input_payload),
            confirmed=confirmed,
            idempotency_key=idempotency_key,
            started_at=started_at,
        )
        try:
            await self.repository.start_tool_execution(log)
        except Exception as exc:
            raise ToolAuditPersistenceError(
                'Tool audit start could not be persisted'
            ) from exc
        if trace is not None:
            await self.record_event(
                trace=trace,
                event_type=TraceEventType.TOOL_STARTED,
                started_at=started_at,
                metadata={
                    'tool_name': tool_name,
                    'tool_call_id': tool_call_id,
                    'input': _detailed_payload(input_payload),
                },
            )
        try:
            result = await operation()
        except Exception as exc:
            completed_at = utc_now()
            error = map_exception(exc, trace_id=trace_id)
            failed = log.model_copy(
                update={
                    'status': ToolExecutionStatus.FAILED,
                    'success': False,
                    'duration_ms': int((perf_counter() - started) * 1000),
                    'error_code': error.code,
                    'error_message': error.message,
                    'completed_at': completed_at,
                }
            )
            try:
                await self.repository.finish_tool_execution(failed)
            except Exception:
                logger.critical(
                    'tool_audit_finish_failed trace_id=%s tool_call_id=%s '
                    'tool_name=%s outcome=failed',
                    trace_id,
                    tool_call_id,
                    tool_name,
                    exc_info=True,
                )
            if trace is not None:
                await self.record_event(
                    trace=trace,
                    event_type=TraceEventType.TOOL_COMPLETED,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=failed.duration_ms,
                    success=False,
                    error_code=error.code,
                    metadata={
                        'tool_name': tool_name,
                        'tool_call_id': tool_call_id,
                        'error': error.model_dump(mode='json'),
                    },
                )
            raise
        completed_at = utc_now()
        succeeded = log.model_copy(
            update={
                'status': ToolExecutionStatus.SUCCEEDED,
                'success': True,
                'output_payload': _detailed_payload(result),
                'duration_ms': int((perf_counter() - started) * 1000),
                'completed_at': completed_at,
            }
        )
        try:
            await self.repository.finish_tool_execution(succeeded)
        except Exception:
            logger.critical(
                'tool_audit_finish_failed trace_id=%s tool_call_id=%s '
                'tool_name=%s outcome=succeeded',
                trace_id,
                tool_call_id,
                tool_name,
                exc_info=True,
            )
        if trace is not None:
            await self.record_event(
                trace=trace,
                event_type=TraceEventType.TOOL_COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=succeeded.duration_ms,
                success=True,
                metadata={
                    'tool_name': tool_name,
                    'tool_call_id': tool_call_id,
                    'output': _detailed_payload(result),
                },
            )
        return result

    def _trace_from_state(self, state: Mapping[str, Any]) -> TraceRecord | None:
        trace_id = state.get('trace_id')
        if not trace_id:
            return None
        return TraceRecord(
            trace_id=str(trace_id),
            parent_trace_id=(
                str(state['parent_trace_id'])
                if state.get('parent_trace_id')
                else None
            ),
            tenant_id=self.tenant_id,
            user_id=str(state.get('user_id') or ''),
            thread_id=str(state.get('thread_id') or ''),
            request_id=str(state.get('request_id') or state.get('thread_id') or ''),
            operation=str(state.get('trace_operation') or 'chat'),
        )


def _to_data(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, list):
        return [_to_data(item) for item in value]
    if isinstance(value, tuple):
        return [_to_data(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _to_data(item) for key, item in value.items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _detailed_payload(value: Any) -> Any:
    value = _to_data(value)
    if isinstance(value, Mapping):
        return {
            str(key): (
                '[REDACTED]'
                if _is_sensitive_key(str(key))
                else _detailed_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_detailed_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_detailed_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace('-', '_')
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


async def execute_observed_model(
    *,
    component: str,
    attempt: int,
    input_payload: Any,
    operation: Callable[[], Awaitable[T]],
) -> T:
    context = _CURRENT_TRACE.get()
    if context is None:
        return await operation()
    started_at = utc_now()
    started = perf_counter()
    model_call_id = str(uuid4())
    await context.service.record_event(
        trace=context.trace,
        event_type=TraceEventType.MODEL_STARTED,
        started_at=started_at,
        metadata={
            'component': component,
            'attempt': attempt,
            'model_call_id': model_call_id,
            'input': _detailed_payload(input_payload),
        },
    )
    try:
        result = await operation()
    except Exception as exc:
        model_error = (
            ModelOutputInvalidError()
            if isinstance(
                exc,
                (OutputParserException, ValidationError, TypeError, ValueError),
            )
            else ModelUnavailableError()
        )
        error = map_exception(model_error, trace_id=context.trace.trace_id)
        await context.service.record_event(
            trace=context.trace,
            event_type=TraceEventType.MODEL_COMPLETED,
            started_at=started_at,
            completed_at=utc_now(),
            duration_ms=int((perf_counter() - started) * 1000),
            success=False,
            error_code=error.code,
            metadata={
                'component': component,
                'attempt': attempt,
                'model_call_id': model_call_id,
                'exception_type': type(exc).__name__,
                'error': error.model_dump(mode='json'),
            },
        )
        raise
    await context.service.record_event(
        trace=context.trace,
        event_type=TraceEventType.MODEL_COMPLETED,
        started_at=started_at,
        completed_at=utc_now(),
        duration_ms=int((perf_counter() - started) * 1000),
        success=True,
        metadata={
            'component': component,
            'attempt': attempt,
            'model_call_id': model_call_id,
            'output': _detailed_payload(result),
        },
    )
    return result


async def execute_observed_tool(
    observability: ObservabilityService | None,
    *,
    state: Mapping[str, Any],
    tool_name: str,
    input_payload: Mapping[str, Any],
    confirmed: bool = False,
    idempotency_key: str | None = None,
    action_id: str | None = None,
    operation: Callable[[], Awaitable[T]],
) -> T:
    if observability is None:
        return await operation()
    return await observability.execute_tool(
        state=state,
        tool_name=tool_name,
        input_payload=input_payload,
        confirmed=confirmed,
        idempotency_key=idempotency_key,
        action_id=action_id,
        operation=operation,
    )
