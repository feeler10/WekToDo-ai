from typing import Literal

from app.graph.state import TaskAgentState
from app.intent.enums import IntentType

Route = Literal[
    'classify_intent',
    'resolve_query_clarification',
    'resolve_task_selection',
    'parse_task',
    'query_task_data',
    'request_intent_clarification',
    'respond_to_general_chat',
    'respond_feature_unavailable',
    'respond_unknown_intent',
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

def route_from_pending_state(state: TaskAgentState) -> Route:
    route = state.get('pending_route')
    if route == 'selection':
        return 'resolve_task_selection'
    if route == 'clarification':
        return 'resolve_query_clarification'
    if route == 'blocked':
        return 'handle_error'
    return 'classify_intent'


def route_after_query_clarification(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    route = state.get('pending_route')
    if route == 'classify':
        return 'classify_intent'
    if route == 'classified':
        return route_after_classification(state)
    return 'end'


def route_after_task_selection(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    if state.get('pending_route') == 'classify':
        return 'classify_intent'
    if state.get('pending_route') == 'selected_update':
        return 'prepare_status_update'
    return 'end'



def route_after_classification(state: TaskAgentState) -> Route:
    if state.get('error_message'):
        return 'handle_error'
    result = state.get('intent_result') or {}
    if result.get('needs_clarification') is True:
        return 'request_intent_clarification'
    if state.get('intent') == IntentType.CREATE_TASK.value:
        return 'parse_task'
    if state.get('intent') == IntentType.QUERY_TASKS.value:
        return 'query_task_data'
    if state.get('intent') == IntentType.UPDATE_TASK_STATUS.value:
        return 'resolve_task_reference'
    if state.get('intent') in {
        IntentType.UPDATE_TASK.value,
        IntentType.DECOMPOSE_TASK.value,
    }:
        return 'respond_feature_unavailable'
    if state.get('intent') == IntentType.GENERAL_CHAT.value:
        return 'respond_to_general_chat'
    return 'respond_unknown_intent'


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
