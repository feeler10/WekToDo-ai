from datetime import datetime, timezone

import pytest

from app.graph.nodes.classify_intent import classify_intent
from app.intent.enums import IntentType
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService


@pytest.mark.anyio
async def test_classification_injects_clock_and_business_timezone() -> None:
    classifier = FakeIntentClassifier(intent=IntentType.GENERAL_CHAT)
    current_utc = datetime(2026, 8, 2, 15, 30, tzinfo=timezone.utc)

    result = await classify_intent(
        {
            'user_message': '未来三天有哪些任务',
            'thread_id': 'thread-1',
            'user_id': 'user-1',
            'timezone': 'Asia/Shanghai',
        },
        service=IntentRecognitionService(classifier),
        clock=lambda: current_utc,
    )

    context = classifier.calls[0]
    assert context.current_datetime.isoformat() == (
        '2026-08-02T23:30:00+08:00'
    )
    assert context.business_timezone == 'Asia/Shanghai'
    assert context.week_starts_on == 'Monday'
    assert result['intent'] == IntentType.GENERAL_CHAT.value


@pytest.mark.anyio
async def test_classification_rejects_naive_clock() -> None:
    with pytest.raises(ValueError, match='timezone-aware'):
        await classify_intent(
            {'user_message': '查看任务'},
            service=IntentRecognitionService(
                FakeIntentClassifier(intent=IntentType.GENERAL_CHAT)
            ),
            clock=lambda: datetime(2026, 8, 2, 15, 30),
        )

