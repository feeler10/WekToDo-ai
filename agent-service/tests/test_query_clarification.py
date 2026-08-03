from datetime import datetime, timedelta, timezone

from app.intent.enums import ClarificationReason, IntentType, TimeScope
from app.intent.models import IntentRecognitionContext, IntentResult, TaskQueryIntent
from app.schemas.query_context import (
    PendingQueryClarification,
    TaskQueryIntentPatch,
)
from app.schemas.task import TaskStatus
from app.services.query_clarification import merge_query_clarification


NOW = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)
CONTEXT = IntentRecognitionContext(
    message='今天',
    current_datetime=NOW,
    business_timezone='Asia/Shanghai',
)


def _original(query: TaskQueryIntent) -> IntentResult:
    return IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=1,
        reason='query',
        query=query,
        needs_clarification=True,
        clarification_reason=ClarificationReason.MISSING_TIME_SCOPE,
        clarification_question='请选择时间范围',
    )


def test_patch_distinguishes_omitted_fields() -> None:
    patch = TaskQueryIntentPatch(time_scope=TimeScope.TODAY)

    assert patch.model_fields_set == {'time_scope'}
    assert patch.statuses is None


def test_merge_time_patch_preserves_unfinished_statuses_and_revalidates() -> None:
    original = _original(
        TaskQueryIntent(
            time_scope=TimeScope.UNSPECIFIED,
            statuses={
                TaskStatus.TODO,
                TaskStatus.DOING,
                TaskStatus.BLOCKED,
            },
        )
    )

    merged = merge_query_clarification(
        original=original,
        patch=TaskQueryIntentPatch(time_scope=TimeScope.TODAY),
        context=CONTEXT,
    )

    assert merged.query is not None
    assert merged.query.time_scope == TimeScope.TODAY
    assert merged.query.statuses == {
        TaskStatus.TODO,
        TaskStatus.DOING,
        TaskStatus.BLOCKED,
    }
    assert merged.needs_clarification is False
    assert merged.clarification_reason is None


def test_merge_custom_patch_keeps_aware_half_open_range() -> None:
    start = datetime.fromisoformat('2026-07-30T00:00:00+08:00')
    end = datetime.fromisoformat('2026-08-02T00:00:00+08:00')

    merged = merge_query_clarification(
        original=_original(TaskQueryIntent()),
        patch=TaskQueryIntentPatch(
            time_scope=TimeScope.CUSTOM,
            start_at=start,
            end_at=end,
            raw_time_expression='过去三个完整自然日',
        ),
        context=CONTEXT,
    )

    assert merged.query is not None
    assert merged.query.start_at == start
    assert merged.query.end_at == end
    assert merged.query.raw_time_expression == '过去三个完整自然日'
    assert merged.needs_clarification is False


def test_switching_custom_to_today_clears_custom_boundaries() -> None:
    original = _original(
        TaskQueryIntent(
            time_scope=TimeScope.CUSTOM,
            start_at=datetime.fromisoformat('2026-07-30T00:00:00+08:00'),
            end_at=datetime.fromisoformat('2026-08-02T00:00:00+08:00'),
            raw_time_expression='过去三个完整自然日',
        )
    )

    merged = merge_query_clarification(
        original=original,
        patch=TaskQueryIntentPatch(time_scope=TimeScope.TODAY),
        context=CONTEXT,
    )

    assert merged.query is not None
    assert merged.query.time_scope == TimeScope.TODAY
    assert merged.query.start_at is None
    assert merged.query.end_at is None
    assert merged.query.raw_time_expression is None


def test_ambiguous_time_patch_remains_pending() -> None:
    merged = merge_query_clarification(
        original=_original(TaskQueryIntent()),
        patch=TaskQueryIntentPatch(
            time_scope=TimeScope.CUSTOM,
            start_at=None,
            end_at=None,
            raw_time_expression='前三天',
        ),
        context=IntentRecognitionContext(
            message='前三天',
            current_datetime=NOW,
            business_timezone='Asia/Shanghai',
        ),
        clarification_reason=ClarificationReason.AMBIGUOUS_TIME_EXPRESSION,
        clarification_question='请确认前三天的含义',
    )

    assert merged.needs_clarification is True
    assert (
        merged.clarification_reason
        == ClarificationReason.AMBIGUOUS_TIME_EXPRESSION
    )


def test_pending_query_requires_aware_ordered_expiry() -> None:
    pending = PendingQueryClarification(
        user_id='user-1',
        thread_id='thread-1',
        original_intent=_original(TaskQueryIntent()),
        clarification_reason=ClarificationReason.MISSING_TIME_SCOPE,
        missing_fields=['time_scope'],
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )

    assert pending.missing_fields == ['time_scope']
