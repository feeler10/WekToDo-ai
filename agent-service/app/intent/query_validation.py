from app.intent.enums import ClarificationReason, IntentType, TimeScope
from app.intent.models import (
    IntentRecognitionContext,
    IntentResult,
    TaskQueryIntent,
)
from app.intent.task_reference import is_contextual_task_reference
from app.schemas.task import TaskStatus

_UNFINISHED_STATUSES = {
    TaskStatus.TODO,
    TaskStatus.DOING,
    TaskStatus.BLOCKED,
}
def validate_query_completeness(
    result: IntentResult,
    context: IntentRecognitionContext,
) -> IntentResult:
    """Deterministically normalize clarification state for task queries."""
    if result.intent == IntentType.DECOMPOSE_TASK:
        reference = result.task_reference
        if reference is None or is_contextual_task_reference(
            reference, context.message
        ):
            return result.model_copy(
                update={
                    'task_reference': None,
                    'needs_clarification': True,
                    'clarification_reason': (
                        ClarificationReason.MISSING_TASK_REFERENCE
                    ),
                    'clarification_question': (
                        '你想拆解哪个任务？请告诉我任务名称。'
                    ),
                }
            )
        return _without_clarification(result)
    if result.intent != IntentType.QUERY_TASKS:
        return result

    reference = result.task_reference
    if is_contextual_task_reference(reference, context.message):
        return result.model_copy(
            update={
                'task_reference': None,
                'needs_clarification': True,
                'clarification_reason': (
                    ClarificationReason.MISSING_TASK_REFERENCE
                ),
                'clarification_question': (
                    '你指的是哪个任务？请告诉我任务名称。'
                ),
            }
        )

    query = result.query or TaskQueryIntent()
    if query.include_subtasks and reference is None:
        return _with_clarification(
            result,
            query=query,
            reason=ClarificationReason.MISSING_TASK_REFERENCE,
            question='你想查看哪个父任务的子任务？请告诉我任务名称。',
        )
    if (
        result.clarification_reason
        == ClarificationReason.AMBIGUOUS_TIME_EXPRESSION
    ):
        return _with_clarification(
            result,
            query=query,
            reason=ClarificationReason.AMBIGUOUS_TIME_EXPRESSION,
            question=(
                result.clarification_question
                or _ambiguous_time_question(query)
            ),
        )

    if reference is not None and result.query is None:
        return _without_clarification(result)

    if query.time_scope == TimeScope.CUSTOM and not _has_custom_range(query):
        return _with_clarification(
            result,
            query=query,
            reason=ClarificationReason.INVALID_TIME_RANGE,
            question=_invalid_time_range_question(query),
        )

    if reference is not None:
        return _without_clarification(
            result.model_copy(update={'query': query})
        )

    if query.time_scope == TimeScope.UNSPECIFIED:
        return _with_clarification(
            result,
            query=query,
            reason=ClarificationReason.MISSING_TIME_SCOPE,
            question=_time_scope_question(query),
        )

    return _without_clarification(result.model_copy(update={'query': query}))


def _has_custom_range(query: TaskQueryIntent) -> bool:
    return query.start_at is not None and query.end_at is not None


def _time_scope_question(query: TaskQueryIntent) -> str:
    if query.statuses == _UNFINISHED_STATUSES:
        return (
            '你想查看哪个时间范围内的未完成任务？'
            '例如今天、本周，或者所有未完成任务。'
        )
    return (
        '你想查看哪个时间范围内的任务？'
        '例如今天、本周，或者所有任务。'
    )


def _invalid_time_range_question(query: TaskQueryIntent) -> str:
    if query.raw_time_expression:
        return (
            f'无法确定「{query.raw_time_expression}」的完整时间范围，'
            '请提供更明确的开始和结束时间。'
        )
    return '请提供完整且有效的开始和结束时间。'


def _ambiguous_time_question(query: TaskQueryIntent) -> str:
    if query.raw_time_expression:
        return (
            f'你说的「{query.raw_time_expression}」具体指哪个时间范围？'
            '请提供更明确的开始和结束时间。'
        )
    return '这个时间表达有多种解释，请提供更明确的时间范围。'


def _with_clarification(
    result: IntentResult,
    *,
    query: TaskQueryIntent,
    reason: ClarificationReason,
    question: str,
) -> IntentResult:
    return result.model_copy(
        update={
            'query': query,
            'needs_clarification': True,
            'clarification_reason': reason,
            'clarification_question': question,
        }
    )


def _without_clarification(result: IntentResult) -> IntentResult:
    return result.model_copy(
        update={
            'needs_clarification': False,
            'clarification_reason': None,
            'clarification_question': None,
        }
    )
