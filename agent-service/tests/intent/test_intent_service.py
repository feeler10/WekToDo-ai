import pytest

from app.intent.enums import IntentType
from app.intent.exceptions import (
    InvalidIntentOutputError,
    IntentProviderUnavailableError,
)
from app.intent.models import IntentRecognitionContext, IntentResult
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService


@pytest.mark.anyio
async def test_empty_input_does_not_call_provider() -> None:
    classifier = FakeIntentClassifier(error=AssertionError('must not be called'))
    service = IntentRecognitionService(classifier)

    result = await service.recognize(IntentRecognitionContext(message='  '))

    assert result.intent == IntentType.UNKNOWN
    assert result.needs_clarification is True
    assert result.clarification_question
    assert classifier.calls == []


@pytest.mark.anyio
async def test_service_returns_validated_provider_result() -> None:
    expected = IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=0.8,
        reason='用户正在查询任务',
    )
    service = IntentRecognitionService(FakeIntentClassifier(expected))

    assert await service.recognize(
        IntentRecognitionContext(message='今天有什么任务')
    ) == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    'error',
    [
        IntentProviderUnavailableError('offline'),
        InvalidIntentOutputError('bad output'),
    ],
)
async def test_expected_provider_errors_degrade_safely(error: Exception) -> None:
    service = IntentRecognitionService(FakeIntentClassifier(error=error))

    result = await service.recognize(
        IntentRecognitionContext(message='完成论文任务')
    )

    assert result.intent == IntentType.UNKNOWN
    assert result.needs_clarification is False
    assert result.target_status is None
    assert result.reason == '意图识别服务暂时不可用'


@pytest.mark.anyio
async def test_unexpected_programming_error_is_not_swallowed() -> None:
    service = IntentRecognitionService(
        FakeIntentClassifier(error=RuntimeError('bug'))
    )

    with pytest.raises(RuntimeError, match='bug'):
        await service.recognize(IntentRecognitionContext(message='创建任务'))
