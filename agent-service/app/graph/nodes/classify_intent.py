from app.graph.state import TaskAgentState
from app.intent.models import IntentRecognitionContext
from app.intent.service import IntentRecognitionService


async def classify_intent(
    state: TaskAgentState,
    *,
    service: IntentRecognitionService,
) -> dict[str, object]:
    result = await service.recognize(
        IntentRecognitionContext(
            message=state.get('user_message', ''),
            conversation_id=state.get('thread_id'),
            user_id=state.get('user_id'),
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
