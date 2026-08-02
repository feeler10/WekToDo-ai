from typing import Literal

from app.graph.classifier import TaskIntent
from app.graph.state import TaskAgentState

Route = Literal[
    'parse_task',
    'parse_task_reference',
    'query_task_data',
    'resolve_task_reference',
    'validate_task',
    'calculate_priority',
    'prepare_confirmation',
    'request_confirmation',
    'execute_create_task',
    'execute_status_update',
    'prepare_status_update',
    'edit',
    'regenerate',
    'reject',
    'handle_error',
    'end',
]


def route_after_classification(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    if state.get('intent') == TaskIntent.CREATE_TASK.value:
        return 'parse_task'
    if state.get('intent') == TaskIntent.QUERY_TASK.value:
        return 'query_task_data'
    if state.get('intent') == TaskIntent.UPDATE_TASK.value:
        return 'parse_task_reference'
    return 'handle_error'


def route_after_task_reference_parsing(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    return 'resolve_task_reference'


def route_after_query(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    return 'end'


def route_after_task_reference_resolution(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    if state.get('selected_task'):
        return 'prepare_status_update'
    return 'end'


def route_after_parsing(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    return 'validate_task'


def route_after_validation(state: TaskAgentState) -> Route:
    if state.get('error_message') or not state.get('validation_passed'):
        return 'handle_error'
    return 'calculate_priority'


def route_after_priority(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    return 'prepare_confirmation'


def route_after_preparation(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    if not state.get('pending_action'):
        return 'end'
    return 'request_confirmation'


def route_after_confirmation(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    action = state.get('review_action')
    if action == 'approve':
        pending = state.get('pending_action') or {}
        if pending.get('action_type') == 'update_task_status':
            return 'execute_status_update'
        return 'execute_create_task'
    if action == 'edit':
        return 'edit'
    if action == 'regenerate':
        return 'regenerate'
    return 'reject'


def route_after_execution(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    return 'end'
