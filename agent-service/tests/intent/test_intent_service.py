from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.intent.enums import IntentType, TimeScope
from app.intent.exceptions import (
    InvalidIntentOutputError,
    IntentProviderUnavailableError,
)
from app.intent.models import (
    IntentRecognitionContext,
    IntentResult,
    TaskQueryIntent,
)
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
        query=TaskQueryIntent(time_scope=TimeScope.TODAY),
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


@pytest.mark.anyio
@pytest.mark.parametrize('message', ['最近五天的任务', '近5天有哪些任务'])
async def test_service_normalizes_recent_days_as_upcoming_calendar_days(
    message: str,
) -> None:
    provider_result = IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=0.9,
        reason='用户正在查询最近几天的任务',
        query=TaskQueryIntent(
            time_scope=TimeScope.CUSTOM,
            start_at=datetime.fromisoformat('2026-07-31T00:00:00+08:00'),
            end_at=datetime.fromisoformat('2026-08-05T00:00:00+08:00'),
            raw_time_expression='最近五天',
        ),
    )
    service = IntentRecognitionService(FakeIntentClassifier(provider_result))

    result = await service.recognize(
        IntentRecognitionContext(
            message=message,
            current_datetime=datetime.fromisoformat(
                '2026-08-04T16:30:00+08:00'
            ),
            business_timezone='Asia/Shanghai',
        )
    )

    assert result.query is not None
    assert result.query.start_at == datetime(
        2026, 8, 4, tzinfo=ZoneInfo('Asia/Shanghai')
    )
    assert result.query.end_at == datetime(
        2026, 8, 9, tzinfo=ZoneInfo('Asia/Shanghai')
    )
    assert result.needs_clarification is False


@pytest.mark.anyio
async def test_service_does_not_rewrite_explicit_past_days() -> None:
    start = datetime.fromisoformat('2026-07-30T00:00:00+08:00')
    end = datetime.fromisoformat('2026-08-04T00:00:00+08:00')
    provider_result = IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=0.9,
        reason='用户正在查询过去的任务',
        query=TaskQueryIntent(
            time_scope=TimeScope.CUSTOM,
            start_at=start,
            end_at=end,
            raw_time_expression='过去五天',
        ),
    )
    service = IntentRecognitionService(FakeIntentClassifier(provider_result))

    result = await service.recognize(
        IntentRecognitionContext(
            message='过去五天的任务',
            current_datetime=datetime.fromisoformat(
                '2026-08-04T16:30:00+08:00'
            ),
            business_timezone='Asia/Shanghai',
        )
    )

    assert result.query is not None
    assert result.query.start_at == start
    assert result.query.end_at == end
