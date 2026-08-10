from collections.abc import Mapping
from datetime import datetime
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.builder import GraphDependencies, build_task_graph
from tests.intent_helpers import existing_flow_intent_service
from app.intent.enums import IntentType
from app.schemas.task import TaskPriority


class FakeParser:
    def __init__(
        self,
        result: Mapping[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or {}
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        self.calls.append((user_message, timezone))
        if self.error is not None:
            raise self.error
        return self.result


def initial_state(message: str) -> dict[str, str]:
    return {
        'user_id': 'user-1',
        'thread_id': 'thread-1',
        'user_message': message,
        'timezone': 'Asia/Shanghai',
        'request_id': 'request-1',
    }


@pytest.mark.anyio
async def test_create_task_path_calculates_priority_with_fake_parser() -> None:
    parser = FakeParser(
        {
            'title': '完成论文实验',
            'description': '重新运行实验并更新表格',
            'deadline_score': 100,
            'semantic_importance': 80,
            'impact_score': 50,
            'workload_risk_score': 40,
            'dependency_score': 20,
            'priority_reason': '明确截止时间且影响论文进度',
        }
    )
    graph = build_task_graph(
        GraphDependencies(intent_service=existing_flow_intent_service(), parser=parser),
        checkpointer=InMemorySaver(),
    )

    result = await graph.ainvoke(
        initial_state('创建一个论文实验任务'),
        config={'configurable': {'thread_id': 'thread-1'}},
    )

    assert result['intent'] == IntentType.CREATE_TASK.value
    assert result['parsed_task']['user_id'] == 'user-1'
    assert result['parsed_task']['title'] == '完成论文实验'
    assert result['validation_passed'] is True
    assert result['urgency_score'] == 75
    assert result['ai_priority'] == TaskPriority.HIGH.value
    assert result['priority_reason'] == '明确截止时间且影响论文进度'
    assert result['error_message'] is None
    assert result['__interrupt__'][0].value['type'] == 'task_confirmation'
    assert parser.calls == [('创建一个论文实验任务', 'Asia/Shanghai')]


@pytest.mark.anyio
async def test_query_intent_routes_without_task_parser() -> None:
    parser = FakeParser({'title': 'Should not be parsed'})
    graph = build_task_graph(GraphDependencies(intent_service=existing_flow_intent_service(), parser=parser))

    result = await graph.ainvoke(initial_state('查询我今天的任务'))

    assert result['intent'] == IntentType.QUERY_TASKS.value
    assert result['final_response'] == 'Task repository is not configured'
    assert parser.calls == []


@pytest.mark.anyio
async def test_missing_title_routes_validation_error() -> None:
    parser = FakeParser({'description': 'No title'})
    graph = build_task_graph(GraphDependencies(intent_service=existing_flow_intent_service(), parser=parser))

    result = await graph.ainvoke(initial_state('创建一个任务'))

    assert result['validation_passed'] is False
    assert result['missing_fields'] == ['title']
    assert result['error_message'] == 'Task validation failed'
    assert result['final_response'] == 'Task validation failed'
    assert 'urgency_score' not in result


@pytest.mark.anyio
async def test_naive_deadline_routes_validation_error() -> None:
    parser = FakeParser(
        {
            'title': 'Invalid time task',
            'deadline': datetime(2026, 8, 7, 23, 59),
        }
    )
    graph = build_task_graph(GraphDependencies(intent_service=existing_flow_intent_service(), parser=parser))

    result = await graph.ainvoke(initial_state('创建一个任务'))

    assert result['validation_passed'] is False
    assert result['error_message'] == 'Task validation failed'
    assert any('timezone' in error for error in result['validation_errors'])


@pytest.mark.anyio
async def test_parser_exception_routes_to_handle_error() -> None:
    parser = FakeParser(error=RuntimeError('parser unavailable'))
    graph = build_task_graph(GraphDependencies(intent_service=existing_flow_intent_service(), parser=parser))

    result = await graph.ainvoke(initial_state('创建一个任务'))

    assert result['error_message'] == 'Task parsing failed: parser unavailable'
    assert result['final_response'] == 'Task parsing failed: parser unavailable'


def test_graph_contains_expected_nodes_and_edges() -> None:
    graph = build_task_graph(GraphDependencies(intent_service=existing_flow_intent_service(), parser=FakeParser()))
    representation = graph.get_graph()

    assert set(representation.nodes) == {
        '__start__',
        'classify_intent',
        'parse_task',
        'parse_task_update',
        'route_pending_state',
        'resolve_query_clarification',
        'resolve_task_selection',
        'validate_task',
        'calculate_priority',
        'handle_error',
        'prepare_confirmation',
        'request_confirmation',
        'execute_create_task',
        'query_task_data',
        'resolve_task_reference',
        'prepare_status_update',
        'execute_status_update',
        'execute_task_update',
        'prepare_task_update',
        'request_intent_clarification',
        'respond_feature_unavailable',
        'respond_to_general_chat',
        'respond_unknown_intent',
        '__end__',
    }

    edges = {(edge.source, edge.target) for edge in representation.edges}
    assert {
        ('__start__', 'route_pending_state'),
        ('route_pending_state', 'classify_intent'),
        ('route_pending_state', 'resolve_query_clarification'),
        ('route_pending_state', 'resolve_task_selection'),
        ('resolve_task_selection', 'prepare_status_update'),
        ('resolve_task_selection', 'parse_task_update'),
        ('resolve_task_selection', '__end__'),
        ('resolve_query_clarification', 'query_task_data'),
        ('classify_intent', 'parse_task'),
        ('classify_intent', 'query_task_data'),
        ('classify_intent', 'resolve_task_reference'),
        ('classify_intent', 'request_intent_clarification'),
        ('classify_intent', 'respond_feature_unavailable'),
        ('classify_intent', 'respond_to_general_chat'),
        ('classify_intent', 'respond_unknown_intent'),
        ('classify_intent', 'handle_error'),
        ('parse_task', 'validate_task'),
        ('parse_task', 'handle_error'),
        ('validate_task', 'calculate_priority'),
        ('validate_task', 'handle_error'),
        ('calculate_priority', 'handle_error'),
        ('calculate_priority', 'prepare_confirmation'),
        ('prepare_confirmation', 'request_confirmation'),
        ('prepare_confirmation', 'handle_error'),
        ('request_confirmation', 'execute_create_task'),
        ('request_confirmation', 'validate_task'),
        ('request_confirmation', 'parse_task'),
        ('request_confirmation', '__end__'),
        ('request_confirmation', 'handle_error'),
        ('execute_create_task', '__end__'),
        ('execute_create_task', 'handle_error'),
        ('query_task_data', '__end__'),
        ('query_task_data', 'handle_error'),
        ('resolve_task_reference', 'prepare_status_update'),
        ('resolve_task_reference', 'parse_task_update'),
        ('resolve_task_reference', '__end__'),
        ('resolve_task_reference', 'handle_error'),
        ('prepare_status_update', 'request_confirmation'),
        ('prepare_status_update', '__end__'),
        ('prepare_status_update', 'handle_error'),
        ('parse_task_update', 'prepare_task_update'),
        ('parse_task_update', '__end__'),
        ('parse_task_update', 'handle_error'),
        ('prepare_task_update', 'request_confirmation'),
        ('prepare_task_update', '__end__'),
        ('prepare_task_update', 'handle_error'),
        ('request_confirmation', 'execute_status_update'),
        ('request_confirmation', 'execute_task_update'),
        ('execute_status_update', '__end__'),
        ('execute_status_update', 'handle_error'),
        ('execute_task_update', '__end__'),
        ('execute_task_update', 'handle_error'),
        ('handle_error', '__end__'),
        ('request_intent_clarification', '__end__'),
        ('respond_feature_unavailable', '__end__'),
        ('respond_to_general_chat', '__end__'),
        ('respond_unknown_intent', '__end__'),
    }.issubset(edges)
