from app.graph.state import TaskAgentState
from app.schemas.priority import UrgencyFactors
from app.services.priority import calculate_urgency


def calculate_priority(state: TaskAgentState) -> dict[str, object]:
    try:
        factors = UrgencyFactors.model_validate(state.get('priority_factors', {}))
        result = calculate_urgency(factors)
    except Exception as exc:
        return {'error_message': f'Priority calculation failed: {exc}'}

    reason = state.get('priority_reason') or (
        'Calculated from deadline, importance, impact, workload risk, '
        'and dependency scores'
    )
    return {
        'urgency_score': result.urgency_score,
        'ai_priority': result.priority.value,
        'priority_reason': reason,
        'error_message': None,
    }
