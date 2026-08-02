from app.graph.classifier import IntentClassifier
from app.graph.state import TaskAgentState


def classify_intent(
    state: TaskAgentState,
    *,
    classifier: IntentClassifier,
) -> dict[str, object]:
    try:
        result = classifier.classify(state.get('user_message', ''))
    except Exception as exc:
        return {'error_message': f'Intent classification failed: {exc}'}
    return {
        'intent': result.intent.value,
        'intent_confidence': result.confidence,
        'error_message': None,
    }
