from collections.abc import Callable
from datetime import datetime

from app.graph.state import TaskAgentState
from app.intent.enums import ClarificationReason, IntentType
from app.intent.models import IntentResult
from app.services.task_context import restore_active_task_context


_CLARIFICATION_QUESTIONS = {
    IntentType.QUERY_TASKS: '你指的是哪个任务？请告诉我任务名称。',
    IntentType.UPDATE_TASK_STATUS: '你想更新哪个任务的状态？请告诉我任务名称。',
    IntentType.UPDATE_TASK: '你想修改哪个任务？请告诉我任务名称。',
    IntentType.DECOMPOSE_TASK: '你想拆解哪个任务？请告诉我任务名称。',
}


def resolve_context_reference(
    state: TaskAgentState,
    *,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    now = clock()
    result = IntentResult.model_validate(state.get('intent_result'))
    context = restore_active_task_context(
        state.get('active_task_context'),
        user_id=state['user_id'],
        thread_id=state['thread_id'],
        now=now,
    )
    if context is None:
        clarified = result.model_copy(
            update={
                'task_reference': None,
                'needs_clarification': True,
                'clarification_reason': (
                    result.clarification_reason
                    or ClarificationReason.MISSING_TASK_REFERENCE
                ),
                'clarification_question': (
                    result.clarification_question
                    or _CLARIFICATION_QUESTIONS[result.intent]
                ),
            }
        )
        return {
            'active_task_context': None,
            'intent_result': clarified.model_dump(mode='json'),
            'task_reference': None,
            'error_message': None,
        }

    resolved = result.model_copy(
        update={
            'task_reference': context.task_id,
            'needs_clarification': False,
            'clarification_reason': None,
            'clarification_question': None,
        }
    )
    return {
        'active_task_context': context.model_dump(mode='json'),
        'intent_result': resolved.model_dump(mode='json'),
        'task_reference': context.task_id,
        'error_message': None,
    }
