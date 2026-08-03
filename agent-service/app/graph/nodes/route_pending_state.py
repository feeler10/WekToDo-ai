import logging
from collections.abc import Callable
from datetime import datetime

from app.graph.state import TaskAgentState
from app.schemas.query_context import (
    PendingQueryClarification,
    PendingTaskSelection,
)

logger = logging.getLogger(__name__)


def route_pending_state(
    state: TaskAgentState,
    *,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('clock must return a timezone-aware datetime')

    selection_data = state.get('pending_task_selection')
    if state.get('pending_action'):
        logger.warning(
            'PendingAction blocked ordinary graph entry user_id=%s '
            'thread_id=%s',
            state.get('user_id'),
            state.get('thread_id'),
        )
        return {
            'pending_task_selection': None,
            'pending_query_clarification': None,
            'pending_route': 'blocked',
            'error_message': '当前有待确认的任务操作，请先完成确认或取消。',
        }
    clarification_data = state.get('pending_query_clarification')
    if selection_data:
        selection = PendingTaskSelection.model_validate(selection_data)
        if not _belongs_to_state(selection.user_id, selection.thread_id, state):
            logger.warning(
                'Discarded mismatched pending selection user_id=%s thread_id=%s',
                state.get('user_id'),
                state.get('thread_id'),
            )
            return {
                'pending_task_selection': None,
                'pending_query_clarification': None,
                'pending_route': 'classify',
            }
        update: dict[str, object] = {'pending_route': 'selection'}
        if clarification_data:
            logger.warning(
                'Cleared lower-priority pending clarification user_id=%s '
                'thread_id=%s',
                state.get('user_id'),
                state.get('thread_id'),
            )
            update['pending_query_clarification'] = None
        return update

    if clarification_data:
        clarification = PendingQueryClarification.model_validate(
            clarification_data
        )
        if not _belongs_to_state(
            clarification.user_id,
            clarification.thread_id,
            state,
        ):
            logger.warning(
                'Discarded mismatched pending clarification user_id=%s '
                'thread_id=%s',
                state.get('user_id'),
                state.get('thread_id'),
            )
            return {
                'pending_query_clarification': None,
                'pending_route': 'classify',
            }
        return {'pending_route': 'clarification'}

    return {'pending_route': 'classify'}


def _belongs_to_state(
    user_id: str,
    thread_id: str,
    state: TaskAgentState,
) -> bool:
    return (
        user_id == state.get('user_id')
        and thread_id == state.get('thread_id')
    )
