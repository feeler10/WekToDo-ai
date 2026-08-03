import logging
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from app.graph.state import TaskAgentState
from app.intent.enums import ClarificationReason
from app.intent.models import IntentRecognitionContext, IntentResult
from app.intent.service import IntentRecognitionService
from app.schemas.query_context import (
    PendingQueryClarification,
    missing_fields_for_reason,
)
from app.services.query_clarification import (
    is_explicit_new_request,
    merge_query_clarification,
    query_patch_from_result,
)
from app.services.task_response import (
    format_cancelled_response,
    format_query_clarification,
)
from app.services.task_selection import is_pending_cancellation

logger = logging.getLogger(__name__)


async def resolve_query_clarification(
    state: TaskAgentState,
    *,
    service: IntentRecognitionService,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    pending = PendingQueryClarification.model_validate(
        state.get('pending_query_clarification')
    )
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('clock must return a timezone-aware datetime')
    if pending.expires_at <= now:
        logger.info(
            'Pending clarification expired user_id=%s thread_id=%s',
            state.get('user_id'),
            state.get('thread_id'),
        )
        return {
            'pending_query_clarification': None,
            'pending_route': 'classify',
        }

    message = state.get('user_message', '')
    if is_pending_cancellation(message):
        return {
            'pending_query_clarification': None,
            'pending_route': 'handled',
            'intent_result': None,
            'final_response': format_cancelled_response('查询'),
            'error_message': None,
        }

    business_timezone = state.get('timezone', 'UTC')
    context = IntentRecognitionContext(
        message=message,
        conversation_id=state.get('thread_id'),
        user_id=state.get('user_id'),
        current_datetime=now.astimezone(ZoneInfo(business_timezone)),
        business_timezone=business_timezone,
        week_starts_on='Monday',
    )
    followup = await service.recognize(context)
    if is_explicit_new_request(followup, message):
        logger.info(
            'Pending clarification replaced by new request user_id=%s '
            'thread_id=%s intent=%s',
            state.get('user_id'),
            state.get('thread_id'),
            followup.intent.value,
        )
        return {
            **_classified_result(followup),
            'pending_query_clarification': None,
            'pending_route': 'classified',
        }

    patch = query_patch_from_result(followup)
    if patch is None:
        return {
            'pending_route': 'handled',
            'final_response': format_query_clarification(
                reason=pending.clarification_reason,
                question=pending.original_intent.clarification_question,
            ),
            'error_message': None,
        }

    merged = merge_query_clarification(
        original=pending.original_intent,
        patch=patch,
        context=context,
        clarification_reason=followup.clarification_reason,
        clarification_question=followup.clarification_question,
    )
    logger.info(
        'Merged query clarification user_id=%s thread_id=%s fields=%s',
        state.get('user_id'),
        state.get('thread_id'),
        sorted(patch.model_fields_set),
    )
    if merged.needs_clarification:
        reason = (
            merged.clarification_reason
            or ClarificationReason.UNRESOLVED_CONTEXT
        )
        updated = pending.model_copy(
            update={
                'original_intent': merged,
                'clarification_reason': reason,
                'missing_fields': missing_fields_for_reason(reason),
            }
        )
        return {
            **_classified_result(merged),
            'pending_query_clarification': updated.model_dump(mode='json'),
            'pending_route': 'handled',
            'final_response': format_query_clarification(
                reason=reason,
                question=merged.clarification_question,
            ),
        }

    return {
        **_classified_result(merged),
        'pending_query_clarification': None,
        'pending_route': 'classified',
    }


def _classified_result(result: IntentResult) -> dict[str, object]:
    return {
        'intent_result': result.model_dump(mode='json'),
        'intent': result.intent.value,
        'intent_confidence': result.confidence,
        'task_reference': result.task_reference,
        'target_status': (
            result.target_status.value
            if result.target_status is not None
            else None
        ),
        'final_response': None,
        'error_message': None,
    }
