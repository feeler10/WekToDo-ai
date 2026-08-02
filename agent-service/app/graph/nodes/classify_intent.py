from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from app.graph.state import TaskAgentState
from app.intent.models import IntentRecognitionContext
from app.intent.service import IntentRecognitionService


async def classify_intent(
    state: TaskAgentState,
    *,
    service: IntentRecognitionService,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    current_datetime = clock()
    if current_datetime.tzinfo is None or current_datetime.utcoffset() is None:
        raise ValueError('clock must return a timezone-aware datetime')
    business_timezone = state.get('timezone', 'UTC')
    result = await service.recognize(
        IntentRecognitionContext(
            message=state.get('user_message', ''),
            conversation_id=state.get('thread_id'),
            user_id=state.get('user_id'),
            current_datetime=current_datetime.astimezone(
                ZoneInfo(business_timezone)
            ),
            business_timezone=business_timezone,
            week_starts_on='Monday',
        )
    )
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
        'error_message': None,
    }
