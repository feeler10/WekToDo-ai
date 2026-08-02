import pytest
from pydantic import ValidationError

from app.schemas.priority import UrgencyFactors
from app.schemas.task import TaskPriority
from app.services.priority import calculate_urgency, priority_for_score


def test_calculate_urgency_uses_documented_weights() -> None:
    factors = UrgencyFactors(
        deadline_score=100,
        semantic_importance=80,
        impact_score=50,
        workload_risk_score=40,
        dependency_score=20,
    )

    result = calculate_urgency(factors)

    assert result.urgency_score == 75
    assert result.priority == TaskPriority.HIGH


def test_calculate_urgency_rounds_half_up() -> None:
    factors = UrgencyFactors(
        deadline_score=0,
        semantic_importance=0,
        impact_score=0,
        workload_risk_score=0,
        dependency_score=10,
    )

    assert calculate_urgency(factors).urgency_score == 1


@pytest.mark.parametrize(
    ('score', 'expected'),
    [
        (0, TaskPriority.LOW),
        (29, TaskPriority.LOW),
        (30, TaskPriority.MEDIUM),
        (59, TaskPriority.MEDIUM),
        (60, TaskPriority.HIGH),
        (79, TaskPriority.HIGH),
        (80, TaskPriority.URGENT),
        (100, TaskPriority.URGENT),
    ],
)
def test_priority_boundaries(score: int, expected: TaskPriority) -> None:
    assert priority_for_score(score) == expected


@pytest.mark.parametrize('score', [-1, 101])
def test_priority_rejects_out_of_range_score(score: int) -> None:
    with pytest.raises(ValueError, match='between 0 and 100'):
        priority_for_score(score)


def test_urgency_factors_reject_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        UrgencyFactors(
            deadline_score=101,
            semantic_importance=0,
            impact_score=0,
            workload_risk_score=0,
            dependency_score=0,
        )
