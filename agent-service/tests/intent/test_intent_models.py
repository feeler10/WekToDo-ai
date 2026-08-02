import pytest
from pydantic import ValidationError

from app.intent.enums import IntentType
from app.intent.models import IntentResult
from app.schemas.task import TaskStatus


def test_valid_status_update_result() -> None:
    result = IntentResult(
        intent=IntentType.UPDATE_TASK_STATUS,
        confidence=0.92,
        reason='用户明确要求完成任务',
        task_reference='论文实验',
        target_status=TaskStatus.DONE,
    )

    assert result.target_status == TaskStatus.DONE


@pytest.mark.parametrize('confidence', [-0.1, 1.1])
def test_confidence_must_be_in_range(confidence: float) -> None:
    with pytest.raises(ValidationError):
        IntentResult(
            intent=IntentType.CREATE_TASK,
            confidence=confidence,
            reason='创建任务',
        )


@pytest.mark.parametrize(
    'payload',
    [
        {'intent': 'DELETE_ALL_TASKS', 'confidence': 1, 'reason': '非法'},
        {
            'intent': 'CREATE_TASK',
            'confidence': 1,
            'reason': '创建',
            'extra_field': True,
        },
        {'intent': 'CREATE_TASK', 'confidence': 1, 'reason': ''},
        {'intent': 'CREATE_TASK', 'confidence': 1, 'reason': 'x' * 201},
        {
            'intent': 'CREATE_TASK',
            'confidence': 1,
            'reason': '创建',
            'needs_clarification': True,
        },
        {
            'intent': 'CREATE_TASK',
            'confidence': 1,
            'reason': '创建',
            'clarification_question': '创建什么？',
        },
        {
            'intent': 'QUERY_TASKS',
            'confidence': 1,
            'reason': '查询',
            'target_status': 'DONE',
        },
        {
            'intent': 'UPDATE_TASK_STATUS',
            'confidence': 1,
            'reason': '更新状态',
        },
        {
            'intent': 'UPDATE_TASK_STATUS',
            'confidence': 1,
            'reason': '更新状态',
            'target_status': 'NOT_A_STATUS',
        },
    ],
)
def test_invalid_intent_results_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        IntentResult.model_validate(payload)
