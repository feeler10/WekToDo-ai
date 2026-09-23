from datetime import timedelta

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.repositories.exceptions import (
    IdempotencyConflictError,
    ObservabilityRepositoryConsistencyError,
    TaskVersionConflictError,
    ToolAuditPersistenceError,
)
from app.repositories.observability import ObservabilityRepository
from app.repositories.redis_observability import RedisObservabilityRepository
from app.schemas.audit import (
    ToolExecutionLog,
    ToolExecutionStatus,
)
from app.schemas.trace import (
    TraceEvent,
    TraceEventType,
    TraceRecord,
    TraceStatus,
)
from app.schemas.task import utc_now
from app.services.error_mapping import map_exception
from app.services.observability import (
    ObservabilityService,
    execute_observed_model,
)
from app.core.config import Settings
from app.graph.builder import GraphDependencies, build_task_graph
from app.main import create_app
from app.services.agent import TaskAgentService
from tests.intent_helpers import existing_flow_intent_service
from tests.test_human_in_the_loop import (
    InMemoryTaskRepository,
    SequenceParser,
    _draft,
)


def _trace(*, user_id: str = 'user-1') -> TraceRecord:
    return TraceRecord(
        trace_id='trace-1',
        tenant_id='default',
        user_id=user_id,
        thread_id='thread-1',
        request_id='request-1',
        operation='chat',
    )


@pytest.mark.anyio
async def test_redis_observability_persists_and_isolates_trace_and_tool_log() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisObservabilityRepository(
        redis,
        key_prefix='observability:test',
    )
    trace = _trace()
    now = utc_now()
    event = TraceEvent(
        event_id='event-1',
        trace_id=trace.trace_id,
        tenant_id=trace.tenant_id,
        user_id=trace.user_id,
        thread_id=trace.thread_id,
        sequence=1,
        event_type=TraceEventType.REQUEST_STARTED,
    )
    started = ToolExecutionLog(
        id='tool-1',
        tenant_id=trace.tenant_id,
        user_id=trace.user_id,
        thread_id=trace.thread_id,
        request_id=trace.request_id,
        trace_id=trace.trace_id,
        tool_call_id='tool-1',
        tool_name='query_tasks',
        input_payload={'limit': 100},
        confirmed=False,
        started_at=now,
    )
    try:
        await repository.start_trace(trace)
        await repository.append_trace_event(event)
        await repository.start_tool_execution(started)
        completed_at = now + timedelta(milliseconds=5)
        await repository.finish_tool_execution(
            started.model_copy(
                update={
                    'status': ToolExecutionStatus.SUCCEEDED,
                    'success': True,
                    'output_payload': {'total': 0},
                    'duration_ms': 5,
                    'completed_at': completed_at,
                }
            )
        )
        await repository.finish_trace(
            trace.model_copy(
                update={
                    'status': TraceStatus.SUCCEEDED,
                    'completed_at': utc_now(),
                    'duration_ms': 5,
                }
            )
        )

        restored = await repository.get_trace(
            tenant_id='default',
            user_id='user-1',
            trace_id='trace-1',
        )
        events = await repository.list_trace_events(
            tenant_id='default',
            user_id='user-1',
            trace_id='trace-1',
        )
        logs = await repository.list_tool_executions(
            tenant_id='default',
            user_id='user-1',
            trace_id='trace-1',
        )
        isolated = await repository.get_trace(
            tenant_id='default',
            user_id='user-2',
            trace_id='trace-1',
        )

        assert restored is not None
        assert restored.status == TraceStatus.SUCCEEDED
        assert [item.event_id for item in events] == ['event-1']
        assert len(logs) == 1
        assert logs[0].status == ToolExecutionStatus.SUCCEEDED
        assert isolated is None
        trace_keys = [
            key async for key in redis.scan_iter(match='observability:test:*')
        ]
        assert trace_keys
        ttls = [await redis.ttl(key) for key in trace_keys]
        assert all(ttl > 0 for ttl in ttls)
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_tool_executor_persists_full_business_payload_and_redacts_secrets() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisObservabilityRepository(
        redis,
        key_prefix='observability:tool',
    )
    service = ObservabilityService(repository)
    trace = await service.start_trace(
        user_id='user-1',
        thread_id='thread-1',
        request_id='request-1',
        operation='chat',
    )
    state = {
        'tenant_id': 'default',
        'user_id': 'user-1',
        'thread_id': 'thread-1',
        'request_id': 'request-1',
        'trace_id': trace.trace_id,
    }
    try:
        result = await service.execute_tool(
            state=state,
            tool_name='query_tasks',
            input_payload={
                'user_id': 'user-1',
                'limit': 100,
                'title': '不能进入审计日志的标题',
                'description': '不能进入审计日志的描述',
                'api_key': 'must-not-leak',
            },
            confirmed=False,
            idempotency_key=None,
            action_id=None,
            operation=lambda: _return(
                {
                    'total': 1,
                    'task_ids': ['task-1'],
                    'title': '不能进入输出日志的标题',
                    'authorization': 'Bearer must-not-leak',
                }
            ),
        )
        assert result['total'] == 1

        with pytest.raises(TaskVersionConflictError):
            await service.execute_tool(
                state=state,
                tool_name='update_task',
                input_payload={
                    'task_id': 'task-1',
                    'expected_version': 1,
                },
                confirmed=True,
                idempotency_key='update:request-1',
                action_id='action-1',
                operation=_raise_version_conflict,
            )

        logs = await repository.list_tool_executions(
            tenant_id='default',
            user_id='user-1',
            trace_id=trace.trace_id,
        )
        success = next(item for item in logs if item.tool_name == 'query_tasks')
        failure = next(item for item in logs if item.tool_name == 'update_task')

        assert success.input_payload['title'] == '不能进入审计日志的标题'
        assert success.input_payload['description'] == '不能进入审计日志的描述'
        assert success.input_payload['api_key'] == '[REDACTED]'
        assert success.output_payload == {
            'total': 1,
            'task_ids': ['task-1'],
            'title': '不能进入输出日志的标题',
            'authorization': '[REDACTED]',
        }
        assert failure.status == ToolExecutionStatus.FAILED
        assert failure.error_code == 'task_version_conflict'
        assert failure.error_message == '任务已被修改，请重新查看后再操作。'
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_graph_node_and_each_model_call_persist_detailed_payloads() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisObservabilityRepository(
        redis,
        key_prefix='observability:detailed',
    )
    service = ObservabilityService(repository)
    trace = await service.start_trace(
        user_id='user-1',
        thread_id='thread-1',
        request_id='request-1',
        operation='chat',
        input_payload={
            'message': '看一下所有任务',
            'api_key': 'must-not-leak',
        },
    )
    state = {
        'user_id': 'user-1',
        'thread_id': 'thread-1',
        'request_id': 'request-1',
        'trace_id': trace.trace_id,
        'user_message': '看一下所有任务',
    }

    async def classify(node_state):
        model_result = await execute_observed_model(
            component='intent_classifier',
            attempt=1,
            input_payload={'message': node_state['user_message']},
            operation=lambda: _return(
                {
                    'intent': 'QUERY_TASKS',
                    'confidence': 0.99,
                    'query': {'time_scope': 'ALL'},
                }
            ),
        )
        return {'intent_result': model_result, 'intent': 'QUERY_TASKS'}

    try:
        result = await service.wrap_graph_node('classify_intent', classify)(state)
        assert result['intent'] == 'QUERY_TASKS'
        events = await repository.list_trace_events(
            tenant_id='default',
            user_id='user-1',
            trace_id=trace.trace_id,
        )
        assert [event.sequence for event in events] == list(
            range(1, len(events) + 1)
        )
        request_started = next(
            event
            for event in events
            if event.event_type == TraceEventType.REQUEST_STARTED
        )
        node_started = next(
            event
            for event in events
            if event.event_type == TraceEventType.NODE_STARTED
        )
        model_completed = next(
            event
            for event in events
            if event.event_type == TraceEventType.MODEL_COMPLETED
        )
        node_completed = next(
            event
            for event in events
            if event.event_type == TraceEventType.NODE_COMPLETED
        )

        assert request_started.metadata['input']['message'] == '看一下所有任务'
        assert request_started.metadata['input']['api_key'] == '[REDACTED]'
        assert node_started.metadata['input_state']['user_message'] == '看一下所有任务'
        assert model_completed.metadata['output']['intent'] == 'QUERY_TASKS'
        assert node_completed.metadata['output_patch']['intent'] == 'QUERY_TASKS'
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_audit_start_failure_prevents_tool_execution() -> None:
    repository = FailingAuditRepository()
    service = ObservabilityService(repository)
    called = False

    async def operation() -> dict[str, int]:
        nonlocal called
        called = True
        return {'total': 1}

    with pytest.raises(ToolAuditPersistenceError):
        await service.execute_tool(
            state={
                'user_id': 'user-1',
                'thread_id': 'thread-1',
                'request_id': 'request-1',
                'trace_id': 'trace-1',
            },
            tool_name='delete_task',
            input_payload={'task_id': 'task-1'},
            confirmed=True,
            idempotency_key='delete:request-1',
            action_id='action-1',
            operation=operation,
        )

    assert called is False
    error = map_exception(ToolAuditPersistenceError('failed'))
    assert error.code == 'audit_unavailable'
    assert error.message == '操作审计暂时不可用，为保护数据，本次操作未执行。'
    idempotency = map_exception(IdempotencyConflictError('internal detail'))
    assert idempotency.code == 'idempotency_conflict'
    assert 'internal detail' not in idempotency.message


@pytest.mark.anyio
async def test_audit_finish_failure_does_not_mask_successful_tool() -> None:
    repository = FinishFailingAuditRepository()
    service = ObservabilityService(repository)

    result = await service.execute_tool(
        state={
            'user_id': 'user-1',
            'thread_id': 'thread-1',
            'request_id': 'request-1',
            'trace_id': 'trace-1',
        },
        tool_name='create_task',
        input_payload={'user_id': 'user-1'},
        confirmed=True,
        idempotency_key='create:request-1',
        action_id='action-1',
        operation=lambda: _return({'id': 'task-1', 'status': 'TODO'}),
    )

    assert result == {'id': 'task-1', 'status': 'TODO'}
    assert repository.started is not None


async def _return(value):
    return value


async def _raise_version_conflict():
    raise TaskVersionConflictError('internal English detail')


class FailingAuditRepository(ObservabilityRepository):
    async def start_trace(self, trace: TraceRecord) -> None:
        return None

    async def finish_trace(self, trace: TraceRecord) -> None:
        return None

    async def append_trace_event(self, event: TraceEvent) -> None:
        return None

    async def start_tool_execution(self, log: ToolExecutionLog) -> None:
        raise ObservabilityRepositoryConsistencyError('unavailable')

    async def finish_tool_execution(self, log: ToolExecutionLog) -> None:
        return None

    async def get_trace(self, **kwargs) -> TraceRecord | None:
        return None

    async def list_trace_events(self, **kwargs) -> list[TraceEvent]:
        return []

    async def list_tool_executions(self, **kwargs) -> list[ToolExecutionLog]:
        return []


class FinishFailingAuditRepository(FailingAuditRepository):
    def __init__(self) -> None:
        self.started: ToolExecutionLog | None = None

    async def start_tool_execution(self, log: ToolExecutionLog) -> None:
        self.started = log

    async def finish_tool_execution(self, log: ToolExecutionLog) -> None:
        raise ObservabilityRepositoryConsistencyError('finish failed')


def test_agent_api_returns_trace_and_persists_confirmed_tool_log() -> None:
    redis = FakeRedis(decode_responses=True)
    observability_repository = RedisObservabilityRepository(
        redis,
        key_prefix='observability:api',
    )
    observability = ObservabilityService(observability_repository)
    task_repository = InMemoryTaskRepository()
    graph = build_task_graph(
        GraphDependencies(
            intent_service=existing_flow_intent_service(),
            parser=SequenceParser(_draft('可追踪任务')),
            task_repository=task_repository,
            observability=observability,
        ),
        checkpointer=InMemorySaver(),
    )
    app = create_app(
        Settings(app_env='test'),
        agent_service=TaskAgentService(
            graph,
            observability=observability,
        ),
    )
    with TestClient(app) as client:
        chat = client.post(
            '/api/agent/chat',
            json={
                'user_id': 'user-1',
                'thread_id': 'thread-1',
                'request_id': 'request-1',
                'message': '创建一个可追踪任务',
                'timezone': 'Asia/Shanghai',
            },
        )
        chat_body = chat.json()
        action_id = chat_body['pending_action']['id']
        confirm = client.post(
            '/api/agent/confirm',
            json={
                'user_id': 'user-1',
                'thread_id': 'thread-1',
                'action_id': action_id,
                'action': 'approve',
            },
        )
        confirm_body = confirm.json()
        trace = client.get(
            f"/api/agent/traces/{confirm_body['trace_id']}",
            params={'user_id': 'user-1'},
        )
        isolated = client.get(
            f"/api/agent/traces/{confirm_body['trace_id']}",
            params={'user_id': 'user-2'},
        )
        query = client.post(
            '/api/agent/chat',
            json={
                'user_id': 'user-1',
                'thread_id': 'thread-1',
                'request_id': 'request-2',
                'message': '查看所有任务',
                'timezone': 'Asia/Shanghai',
            },
        )
        query_body = query.json()
        query_trace = client.get(
            f"/api/agent/traces/{query_body['trace_id']}",
            params={'user_id': 'user-1'},
        )

    assert chat.status_code == 200
    assert chat.headers['X-Trace-Id'] == chat_body['trace_id']
    assert confirm.status_code == 200
    assert confirm.headers['X-Trace-Id'] == confirm_body['trace_id']
    assert confirm_body['trace_id'] != chat_body['trace_id']
    assert trace.status_code == 200
    detail = trace.json()
    assert detail['trace']['parent_trace_id'] == chat_body['trace_id']
    assert any(
        event['node_name'] == 'execute_create_task'
        for event in detail['events']
    )
    assert len(detail['tool_executions']) == 1
    tool_log = detail['tool_executions'][0]
    assert tool_log['tool_name'] == 'create_task'
    assert tool_log['confirmed'] is True
    assert tool_log['status'] == 'SUCCEEDED'
    assert tool_log['idempotency_key'] == 'create_task:request-1'
    assert isolated.status_code == 404
    assert query.status_code == 200
    query_detail = query_trace.json()
    query_events = query_detail['events']
    assert [event['sequence'] for event in query_events] == list(
        range(1, len(query_events) + 1)
    )
    assert query_events[0]['metadata']['input']['message'] == '查看所有任务'
    assert any(
        event['node_name'] == 'classify_intent'
        and event['event_type'] == 'NODE_COMPLETED'
        and event['metadata']['output_patch']['intent'] == 'QUERY_TASKS'
        for event in query_events
    )
    assert query_detail['tool_executions'][0]['input_payload']['user_id'] == 'user-1'
    assert query_detail['tool_executions'][0]['output_payload']['items'][0][
        'title'
    ] == '可追踪任务'
    assert query_events[-1]['metadata']['output']['message'].startswith('共找到')
