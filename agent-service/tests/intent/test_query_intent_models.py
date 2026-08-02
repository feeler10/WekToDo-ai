from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.intent.enums import IntentType, TimeScope
from app.intent.models import IntentResult, TaskQueryIntent


def test_task_query_intent_accepts_aware_custom_range() -> None:
    start = datetime(2026, 8, 2, tzinfo=timezone.utc)
    end = datetime(2026, 8, 3, tzinfo=timezone.utc)

    query = TaskQueryIntent(
        time_scope=TimeScope.CUSTOM,
        start_at=start,
        end_at=end,
    )

    assert query.start_at == start
    assert query.end_at == end


@pytest.mark.parametrize(
    'payload',
    [
        {
            'time_scope': 'CUSTOM',
            'start_at': datetime(2026, 8, 2),
        },
        {
            'time_scope': 'CUSTOM',
            'start_at': datetime(2026, 8, 3, tzinfo=timezone.utc),
            'end_at': datetime(2026, 8, 2, tzinfo=timezone.utc),
        },
    ],
)
def test_task_query_intent_rejects_invalid_time(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TaskQueryIntent.model_validate(payload)


def test_non_query_intent_cannot_carry_query() -> None:
    with pytest.raises(ValidationError, match='query is only allowed'):
        IntentResult(
            intent=IntentType.CREATE_TASK,
            confidence=1,
            reason='创建任务',
            query=TaskQueryIntent(time_scope=TimeScope.TODAY),
        )


def test_custom_scope_rejects_empty_range() -> None:
    instant = datetime(2026, 8, 2, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match='later than start_at'):
        TaskQueryIntent(
            time_scope=TimeScope.CUSTOM,
            start_at=instant,
            end_at=instant,
        )


@pytest.mark.parametrize(
    'time_scope',
    [
        TimeScope.TODAY,
        TimeScope.TOMORROW,
        TimeScope.THIS_WEEK,
        TimeScope.OVERDUE,
        TimeScope.ALL,
        TimeScope.UNSPECIFIED,
    ],
)
def test_fixed_scope_rejects_custom_time_bounds(time_scope: TimeScope) -> None:
    with pytest.raises(ValidationError, match='only allowed for CUSTOM'):
        TaskQueryIntent(
            time_scope=time_scope,
            start_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            end_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )


def test_all_and_unspecified_are_valid_without_time_bounds() -> None:
    all_query = TaskQueryIntent(time_scope=TimeScope.ALL)
    unspecified_query = TaskQueryIntent(time_scope=TimeScope.UNSPECIFIED)

    assert all_query.start_at is None and all_query.end_at is None
    assert unspecified_query.start_at is None and unspecified_query.end_at is None


def test_raw_time_expression_is_trimmed() -> None:
    query = TaskQueryIntent(raw_time_expression='  前三天  ')

    assert query.raw_time_expression == '前三天'


def test_custom_scope_preserves_raw_time_expression() -> None:
    query = TaskQueryIntent(
        time_scope=TimeScope.CUSTOM,
        start_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        end_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        raw_time_expression='未来三天',
    )

    assert query.raw_time_expression == '未来三天'
