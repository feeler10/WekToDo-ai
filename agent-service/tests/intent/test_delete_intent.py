import pytest
from pydantic import ValidationError

from app.intent.enums import IntentType
from app.intent.models import IntentRecognitionContext, IntentResult, TaskQueryIntent
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.schemas.task import TaskStatus


@pytest.mark.anyio
async def test_delete_intent_keeps_task_reference_and_no_write_payload() -> None:
    service = IntentRecognitionService(
        FakeIntentClassifier(
            intent=IntentType.DELETE_TASK,
            task_reference='周报任务',
        )
    )
    result = await service.recognize(
        IntentRecognitionContext(message='删除周报任务')
    )
    assert result.intent == IntentType.DELETE_TASK
    assert result.task_reference == '周报任务'
    assert result.target_status is None
    assert result.query is None
    assert result.needs_clarification is False


@pytest.mark.anyio
async def test_delete_intent_defers_reference_validation_to_delete_parser() -> None:
    service = IntentRecognitionService(
        FakeIntentClassifier(
            intent=IntentType.DELETE_TASK,
            task_reference='那个任务',
        )
    )
    result = await service.recognize(
        IntentRecognitionContext(message='删除那个任务')
    )
    assert result.intent == IntentType.DELETE_TASK
    assert result.task_reference == '那个任务'
    assert result.needs_clarification is False


def test_delete_intent_rejects_query_or_target_status_payload() -> None:
    with pytest.raises(ValidationError):
        IntentResult(
            intent=IntentType.DELETE_TASK,
            confidence=1,
            reason='非法查询载荷',
            task_reference='周报',
            query=TaskQueryIntent(),
        )
    with pytest.raises(ValidationError):
        IntentResult(
            intent=IntentType.DELETE_TASK,
            confidence=1,
            reason='非法状态载荷',
            task_reference='周报',
            target_status=TaskStatus.CANCELLED,
        )
