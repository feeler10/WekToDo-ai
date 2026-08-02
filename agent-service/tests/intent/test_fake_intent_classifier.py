import pytest

from app.intent.enums import IntentType
from app.intent.exceptions import IntentProviderUnavailableError
from app.intent.models import IntentRecognitionContext, IntentResult
from app.intent.providers.fake import FakeIntentClassifier


def _result(intent: IntentType) -> IntentResult:
    return IntentResult(intent=intent, confidence=1, reason='测试结果')


@pytest.mark.anyio
async def test_fake_supports_fixed_result_and_records_context() -> None:
    classifier = FakeIntentClassifier(_result(IntentType.CREATE_TASK))
    context = IntentRecognitionContext(message='创建任务', user_id='user-1')

    result = await classifier.classify(context)

    assert result.intent == IntentType.CREATE_TASK
    assert classifier.calls == [context]


@pytest.mark.anyio
async def test_fake_supports_results_by_message() -> None:
    classifier = FakeIntentClassifier(
        responses={
            '你好': _result(IntentType.GENERAL_CHAT),
            '查任务': _result(IntentType.QUERY_TASKS),
        }
    )

    result = await classifier.classify(IntentRecognitionContext(message='查任务'))

    assert result.intent == IntentType.QUERY_TASKS


@pytest.mark.anyio
async def test_fake_can_raise_configured_error() -> None:
    error = IntentProviderUnavailableError('offline')
    classifier = FakeIntentClassifier(error=error)

    with pytest.raises(IntentProviderUnavailableError) as captured:
        await classifier.classify(IntentRecognitionContext(message='创建任务'))

    assert captured.value is error
