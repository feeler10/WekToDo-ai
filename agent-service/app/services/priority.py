from decimal import Decimal, ROUND_HALF_UP

from app.schemas.priority import UrgencyFactors, UrgencyResult
from app.schemas.task import TaskPriority

WEIGHTS = {
    'deadline_score': Decimal('0.40'),
    'semantic_importance': Decimal('0.25'),
    'impact_score': Decimal('0.20'),
    'workload_risk_score': Decimal('0.10'),
    'dependency_score': Decimal('0.05'),
}


def priority_for_score(urgency_score: int) -> TaskPriority:
    if not 0 <= urgency_score <= 100:
        raise ValueError('urgency_score must be between 0 and 100')
    if urgency_score >= 80:
        return TaskPriority.URGENT
    if urgency_score >= 60:
        return TaskPriority.HIGH
    if urgency_score >= 30:
        return TaskPriority.MEDIUM
    return TaskPriority.LOW


def calculate_urgency(factors: UrgencyFactors) -> UrgencyResult:
    weighted_score = sum(
        Decimal(getattr(factors, field_name)) * weight
        for field_name, weight in WEIGHTS.items()
    )
    urgency_score = int(
        weighted_score.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    )
    return UrgencyResult(
        urgency_score=urgency_score,
        priority=priority_for_score(urgency_score),
    )
