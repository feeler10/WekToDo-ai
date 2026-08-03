from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes import (
    calculate_priority,
    classify_intent,
    execute_create_task,
    execute_status_update,
    handle_error,
    parse_task,
    prepare_confirmation,
    prepare_status_update,
    query_task_data,
    request_confirmation,
    request_intent_clarification,
    resolve_query_clarification,
    resolve_task_selection,
    route_pending_state,
    resolve_task_reference,
    respond_feature_unavailable,
    respond_to_general_chat,
    respond_unknown_intent,
    validate_task,
)
from app.graph.parser import TaskParser
from app.graph.routing import (
    route_after_classification,
    route_after_query_clarification,
    route_after_task_selection,
    route_from_pending_state,
    route_after_confirmation,
    route_after_execution,
    route_after_parsing,
    route_after_preparation,
    route_after_priority,
    route_after_query,
    route_after_task_reference_resolution,
    route_after_validation,
)
from app.graph.state import TaskAgentState
from app.intent.service import IntentRecognitionService
from app.matching.base import TaskMatcher
from app.matching.factory import create_task_matcher
from app.repositories.base import TaskRepository
from app.schemas.task import utc_now


@dataclass(frozen=True)
class GraphDependencies:
    parser: TaskParser
    intent_service: IntentRecognitionService
    task_repository: TaskRepository | None = None
    clock: Callable[[], datetime] = utc_now
    task_matcher: TaskMatcher | None = None
    pending_context_ttl_seconds: int = 900


def build_task_graph(
    dependencies: GraphDependencies,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    builder = StateGraph(TaskAgentState)
    task_matcher = dependencies.task_matcher or create_task_matcher()
    pending_ttl = timedelta(
        seconds=dependencies.pending_context_ttl_seconds
    )
    builder.add_node(
        'route_pending_state',
        partial(route_pending_state, clock=dependencies.clock),
    )
    builder.add_node(
        'resolve_query_clarification',
        partial(
            resolve_query_clarification,
            service=dependencies.intent_service,
            clock=dependencies.clock,
        ),
    )
    builder.add_node(
        'resolve_task_selection',
        partial(
            resolve_task_selection,
            repository=dependencies.task_repository,
            clock=dependencies.clock,
        ),
    )
    builder.add_node(
        'classify_intent',
        partial(
            classify_intent,
            service=dependencies.intent_service,
            clock=dependencies.clock,
        ),
    )
    builder.add_node(
        'parse_task',
        partial(parse_task, parser=dependencies.parser),
    )
    builder.add_node('validate_task', validate_task)
    builder.add_node('calculate_priority', calculate_priority)
    builder.add_node(
        'query_task_data',
        partial(
            query_task_data,
            repository=dependencies.task_repository,
            clock=dependencies.clock,
            task_matcher=task_matcher,
            pending_ttl=pending_ttl,
        ),
    )
    builder.add_node(
        'resolve_task_reference',
        partial(
            resolve_task_reference,
            repository=dependencies.task_repository,
            task_matcher=task_matcher,
            clock=dependencies.clock,
            pending_ttl=pending_ttl,
        ),
    )
    builder.add_node('prepare_status_update', prepare_status_update)
    builder.add_node('prepare_confirmation', prepare_confirmation)
    builder.add_node('request_confirmation', request_confirmation)
    builder.add_node(
        'execute_create_task',
        partial(
            execute_create_task,
            repository=dependencies.task_repository,
        ),
    )
    builder.add_node(
        'execute_status_update',
        partial(
            execute_status_update,
            repository=dependencies.task_repository,
        ),
    )
    builder.add_node('handle_error', handle_error)
    builder.add_node(
        'request_intent_clarification',
        partial(
            request_intent_clarification,
            clock=dependencies.clock,
            pending_ttl=pending_ttl,
        ),
    )
    builder.add_node('respond_to_general_chat', respond_to_general_chat)
    builder.add_node(
        'respond_feature_unavailable',
        respond_feature_unavailable,
    )
    builder.add_node('respond_unknown_intent', respond_unknown_intent)

    builder.add_edge(START, 'route_pending_state')
    builder.add_conditional_edges(
        'route_pending_state',
        route_from_pending_state,
        {
            'classify_intent': 'classify_intent',
            'resolve_task_selection': 'resolve_task_selection',
            'resolve_query_clarification': 'resolve_query_clarification',
            'handle_error': 'handle_error',
        },
    )
    builder.add_conditional_edges(
        'resolve_task_selection',
        route_after_task_selection,
        {
            'classify_intent': 'classify_intent',
            'prepare_status_update': 'prepare_status_update',
            'handle_error': 'handle_error',
            'end': END,
        },
    )
    builder.add_conditional_edges(
        'resolve_query_clarification',
        route_after_query_clarification,
        {
            'classify_intent': 'classify_intent',
            'parse_task': 'parse_task',
            'query_task_data': 'query_task_data',
            'resolve_task_reference': 'resolve_task_reference',
            'request_intent_clarification': 'request_intent_clarification',
            'respond_to_general_chat': 'respond_to_general_chat',
            'respond_feature_unavailable': 'respond_feature_unavailable',
            'respond_unknown_intent': 'respond_unknown_intent',
            'handle_error': 'handle_error',
            'end': END,
        },
    )
    builder.add_conditional_edges(
        'classify_intent',
        route_after_classification,
        {
            'parse_task': 'parse_task',
            'query_task_data': 'query_task_data',
            'resolve_task_reference': 'resolve_task_reference',
            'request_intent_clarification': 'request_intent_clarification',
            'respond_to_general_chat': 'respond_to_general_chat',
            'respond_feature_unavailable': 'respond_feature_unavailable',
            'respond_unknown_intent': 'respond_unknown_intent',
            'handle_error': 'handle_error',
        },
    )
    builder.add_conditional_edges(
        'query_task_data',
        route_after_query,
        {
            'handle_error': 'handle_error',
            'end': END,
        },
    )
    builder.add_conditional_edges(
        'resolve_task_reference',
        route_after_task_reference_resolution,
        {
            'prepare_status_update': 'prepare_status_update',
            'handle_error': 'handle_error',
            'end': END,
        },
    )
    builder.add_conditional_edges(
        'prepare_status_update',
        route_after_preparation,
        {
            'request_confirmation': 'request_confirmation',
            'handle_error': 'handle_error',
            'end': END,
        },
    )
    builder.add_conditional_edges(
        'parse_task',
        route_after_parsing,
        {
            'validate_task': 'validate_task',
            'handle_error': 'handle_error',
        },
    )
    builder.add_conditional_edges(
        'validate_task',
        route_after_validation,
        {
            'calculate_priority': 'calculate_priority',
            'handle_error': 'handle_error',
        },
    )
    builder.add_conditional_edges(
        'calculate_priority',
        route_after_priority,
        {
            'handle_error': 'handle_error',
            'prepare_confirmation': 'prepare_confirmation',
        },
    )
    builder.add_conditional_edges(
        'prepare_confirmation',
        route_after_preparation,
        {
            'request_confirmation': 'request_confirmation',
            'handle_error': 'handle_error',
        },
    )
    builder.add_conditional_edges(
        'request_confirmation',
        route_after_confirmation,
        {
            'execute_create_task': 'execute_create_task',
            'execute_status_update': 'execute_status_update',
            'edit': 'validate_task',
            'regenerate': 'parse_task',
            'reject': END,
            'handle_error': 'handle_error',
        },
    )
    builder.add_conditional_edges(
        'execute_create_task',
        route_after_execution,
        {
            'end': END,
            'handle_error': 'handle_error',
        },
    )
    builder.add_conditional_edges(
        'execute_status_update',
        route_after_execution,
        {
            'end': END,
            'handle_error': 'handle_error',
        },
    )
    builder.add_edge('handle_error', END)
    builder.add_edge('request_intent_clarification', END)
    builder.add_edge('respond_to_general_chat', END)
    builder.add_edge('respond_feature_unavailable', END)
    builder.add_edge('respond_unknown_intent', END)
    return builder.compile(checkpointer=checkpointer)
