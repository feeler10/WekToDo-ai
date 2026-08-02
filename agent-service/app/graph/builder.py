from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.classifier import IntentClassifier, KeywordIntentClassifier
from app.graph.nodes import (
    calculate_priority,
    classify_intent,
    execute_create_task,
    execute_status_update,
    handle_error,
    parse_task,
    parse_task_reference,
    prepare_confirmation,
    prepare_status_update,
    query_task_data,
    request_confirmation,
    resolve_task_reference,
    validate_task,
)
from app.graph.parser import TaskParser
from app.graph.routing import (
    route_after_classification,
    route_after_confirmation,
    route_after_execution,
    route_after_parsing,
    route_after_preparation,
    route_after_priority,
    route_after_query,
    route_after_task_reference_parsing,
    route_after_task_reference_resolution,
    route_after_validation,
)
from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.task import utc_now


@dataclass(frozen=True)
class GraphDependencies:
    parser: TaskParser
    classifier: IntentClassifier = field(default_factory=KeywordIntentClassifier)
    task_repository: TaskRepository | None = None
    clock: Callable[[], datetime] = utc_now


def build_task_graph(
    dependencies: GraphDependencies,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    builder = StateGraph(TaskAgentState)
    builder.add_node(
        'classify_intent',
        partial(classify_intent, classifier=dependencies.classifier),
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
        ),
    )
    builder.add_node('parse_task_reference', parse_task_reference)
    builder.add_node(
        'resolve_task_reference',
        partial(
            resolve_task_reference,
            repository=dependencies.task_repository,
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

    builder.add_edge(START, 'classify_intent')
    builder.add_conditional_edges(
        'classify_intent',
        route_after_classification,
        {
            'parse_task': 'parse_task',
            'query_task_data': 'query_task_data',
            'parse_task_reference': 'parse_task_reference',
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
        'parse_task_reference',
        route_after_task_reference_parsing,
        {
            'resolve_task_reference': 'resolve_task_reference',
            'handle_error': 'handle_error',
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
    return builder.compile(checkpointer=checkpointer)
