from app.intent.enums import ClarificationReason, IntentType, TimeScope
from app.intent.models import (
    IntentRecognitionContext,
    IntentResult,
    TaskQueryIntent,
)
from app.intent.query_validation import validate_query_completeness
from app.schemas.query_context import TaskQueryIntentPatch


def query_patch_from_result(
    result: IntentResult,
) -> TaskQueryIntentPatch | None:
    if result.intent != IntentType.QUERY_TASKS:
        return None

    values: dict[str, object] = {}
    if result.task_reference is not None:
        values['task_reference'] = result.task_reference

    query = result.query
    if query is not None:
        has_time = (
            query.time_scope != TimeScope.UNSPECIFIED
            or query.start_at is not None
            or query.end_at is not None
            or query.raw_time_expression is not None
        )
        if has_time:
            values['time_scope'] = query.time_scope
            values['start_at'] = query.start_at
            values['end_at'] = query.end_at
            values['raw_time_expression'] = query.raw_time_expression
        if query.statuses is not None:
            values['statuses'] = query.statuses
        if query.priorities is not None:
            values['priorities'] = query.priorities

    if not values:
        return None
    return TaskQueryIntentPatch.model_validate(values)


def merge_query_clarification(
    *,
    original: IntentResult,
    patch: TaskQueryIntentPatch,
    context: IntentRecognitionContext,
    clarification_reason: ClarificationReason | None = None,
    clarification_question: str | None = None,
) -> IntentResult:
    if original.intent != IntentType.QUERY_TASKS:
        raise ValueError('original intent must be QUERY_TASKS')

    query = original.query or TaskQueryIntent()
    query_values = query.model_dump()
    fields = patch.model_fields_set
    time_fields = {
        'time_scope',
        'start_at',
        'end_at',
        'raw_time_expression',
    }

    if 'time_scope' in fields:
        scope = patch.time_scope
        if scope is None:
            raise ValueError('time_scope patch cannot be null')
        query_values['time_scope'] = scope
        if scope != TimeScope.CUSTOM:
            query_values['start_at'] = None
            query_values['end_at'] = None
        elif query.time_scope != TimeScope.CUSTOM:
            query_values['start_at'] = None
            query_values['end_at'] = None
        query_values['raw_time_expression'] = None

    for field in ('statuses', 'priorities'):
        if field in fields:
            query_values[field] = getattr(patch, field)

    if fields.intersection(time_fields):
        for field in ('start_at', 'end_at', 'raw_time_expression'):
            if field in fields:
                query_values[field] = getattr(patch, field)

    task_reference = original.task_reference
    if 'task_reference' in fields:
        task_reference = patch.task_reference

    merged = original.model_copy(
        update={
            'task_reference': task_reference,
            'query': TaskQueryIntent.model_validate(query_values),
            'needs_clarification': False,
            'clarification_reason': None,
            'clarification_question': None,
        }
    )
    if clarification_reason == ClarificationReason.AMBIGUOUS_TIME_EXPRESSION:
        merged = merged.model_copy(
            update={
                'needs_clarification': True,
                'clarification_reason': clarification_reason,
                'clarification_question': clarification_question,
            }
        )
    return validate_query_completeness(merged, context)


def is_explicit_new_request(
    result: IntentResult,
    message: str,
) -> bool:
    if result.intent != IntentType.QUERY_TASKS:
        return True
