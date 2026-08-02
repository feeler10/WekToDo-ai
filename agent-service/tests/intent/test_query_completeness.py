from datetime import datetime, timedelta, timezone

import pytest

from app.intent.enums import ClarificationReason, IntentType, TimeScope
from app.intent.models import IntentRecognitionContext
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.schemas.task import TaskPriority, TaskStatus

UNFINISHED = {TaskStatus.TODO, TaskStatus.DOING, TaskStatus.BLOCKED}


async def _recognize(
    message: str,
    classifier: FakeIntentClassifier,
):
    return await IntentRecognitionService(classifier).recognize(
        IntentRecognitionContext(message=message)
    )


@pytest.mark.anyio
async def test_today_unfinished_query_is_complete() -> None:
    result = await _recognize(
        '今天有哪些任务没完成',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            confidence=0.99,
            time_scope=TimeScope.TODAY,
            statuses=UNFINISHED,
        ),
    )

    assert result.intent == IntentType.QUERY_TASKS
    assert result.query is not None
    assert result.query.time_scope == TimeScope.TODAY
    assert result.query.statuses == UNFINISHED
    assert result.needs_clarification is False
    assert result.clarification_reason is None


@pytest.mark.anyio
async def test_unspecified_unfinished_query_requires_time_scope() -> None:
    result = await _recognize(
        '有哪些任务没完成',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            confidence=1,
            time_scope=TimeScope.UNSPECIFIED,
            statuses=UNFINISHED,
            needs_clarification=False,
        ),
    )

    assert result.query is not None
    assert result.query.time_scope == TimeScope.UNSPECIFIED
    assert result.query.statuses == UNFINISHED
    assert result.needs_clarification is True
    assert (
        result.clarification_reason
        == ClarificationReason.MISSING_TIME_SCOPE
    )
    assert result.clarification_question == (
        '你想查看哪个时间范围内的未完成任务？'
        '例如今天、本周，或者所有未完成任务。'
    )


@pytest.mark.anyio
async def test_all_unfinished_query_clears_incorrect_llm_clarification() -> None:
    result = await _recognize(
        '查看所有未完成任务',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            time_scope=TimeScope.ALL,
            statuses=UNFINISHED,
            needs_clarification=True,
            clarification_reason=ClarificationReason.MISSING_TIME_SCOPE,
            clarification_question='请补充时间范围。',
        ),
    )

    assert result.query is not None
    assert result.query.time_scope == TimeScope.ALL
    assert result.needs_clarification is False
    assert result.clarification_reason is None
    assert result.clarification_question is None


@pytest.mark.anyio
async def test_specific_task_query_does_not_require_time_scope() -> None:
    result = await _recognize(
        '论文任务完成得怎么样了',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            task_reference=' 论文任务 ',
        ),
    )

    assert result.task_reference == '论文任务'
    assert result.query is None
    assert result.needs_clarification is False


@pytest.mark.anyio
async def test_unresolved_task_reference_requires_task_name() -> None:
    result = await _recognize(
        '那个任务完成得怎么样了',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            task_reference='那个任务',
            time_scope=TimeScope.TODAY,
        ),
    )

    assert result.task_reference is None
    assert result.needs_clarification is True
    assert (
        result.clarification_reason
        == ClarificationReason.MISSING_TASK_REFERENCE
    )
    assert result.clarification_question == (
        '你指的是哪个任务？请告诉我任务名称。'
    )


@pytest.mark.anyio
async def test_query_question_never_uses_target_status() -> None:
    result = await _recognize(
        '论文做完了吗',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            task_reference='论文',
        ),
    )

    assert result.intent == IntentType.QUERY_TASKS
    assert result.task_reference == '论文'
    assert result.target_status is None
    assert result.needs_clarification is False


@pytest.mark.anyio
async def test_status_update_can_use_target_status() -> None:
    result = await _recognize(
        '论文做完了',
        FakeIntentClassifier(
            intent=IntentType.UPDATE_TASK_STATUS,
            task_reference='论文',
            target_status=TaskStatus.DONE,
        ),
    )

    assert result.intent == IntentType.UPDATE_TASK_STATUS
    assert result.target_status == TaskStatus.DONE
    assert result.query is None


@pytest.mark.anyio
async def test_high_confidence_cannot_bypass_missing_time_scope() -> None:
    result = await _recognize(
        '查看高优先级任务',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            confidence=1,
            priorities={TaskPriority.HIGH, TaskPriority.URGENT},
        ),
    )

    assert result.needs_clarification is True
    assert (
        result.clarification_reason
        == ClarificationReason.MISSING_TIME_SCOPE
    )


@pytest.mark.anyio
async def test_custom_scope_requires_both_time_bounds() -> None:
    result = await _recognize(
        '查看八月的任务',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            time_scope=TimeScope.CUSTOM,
            raw_time_expression='八月',
        ),
    )

    assert result.needs_clarification is True
    assert (
        result.clarification_reason
        == ClarificationReason.INVALID_TIME_RANGE
    )
    assert result.query is not None
    assert result.query.raw_time_expression == '八月'


@pytest.mark.anyio
@pytest.mark.parametrize('missing_field', ['start_at', 'end_at'])
async def test_custom_scope_rejects_each_missing_bound(
    missing_field: str,
) -> None:
    start = datetime(2026, 8, 5, tzinfo=timezone.utc)
    end = datetime(2026, 8, 11, tzinfo=timezone.utc)
    result = await _recognize(
        '查看明确日期区间的任务',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            time_scope=TimeScope.CUSTOM,
            start_at=None if missing_field == 'start_at' else start,
            end_at=None if missing_field == 'end_at' else end,
            raw_time_expression='明确日期区间',
        ),
    )

    assert result.needs_clarification is True
    assert (
        result.clarification_reason
        == ClarificationReason.INVALID_TIME_RANGE
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ('message', 'raw_expression', 'start', 'end'),
    [
        (
            '昨天的昨天有什么规划',
            '昨天的昨天',
            datetime(2026, 7, 31, tzinfo=timezone(timedelta(hours=8))),
            datetime(2026, 8, 1, tzinfo=timezone(timedelta(hours=8))),
        ),
        (
            '未来三天有哪些任务',
            '未来三天',
            datetime(2026, 8, 2, tzinfo=timezone(timedelta(hours=8))),
            datetime(2026, 8, 5, tzinfo=timezone(timedelta(hours=8))),
        ),
        (
            '今年 8 月 5 日到 8 月 10 日有哪些任务',
            '今年 8 月 5 日到 8 月 10 日',
            datetime(2026, 8, 5, tzinfo=timezone(timedelta(hours=8))),
            datetime(2026, 8, 11, tzinfo=timezone(timedelta(hours=8))),
        ),
    ],
)
async def test_explicit_natural_language_range_uses_custom(
    message: str,
    raw_expression: str,
    start: datetime,
    end: datetime,
) -> None:
    result = await _recognize(
        message,
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            time_scope=TimeScope.CUSTOM,
            start_at=start,
            end_at=end,
            raw_time_expression=raw_expression,
        ),
    )

    assert result.query is not None
    assert result.query.time_scope == TimeScope.CUSTOM
    assert result.query.raw_time_expression == raw_expression
    assert result.query.start_at == start
    assert result.query.end_at == end
    assert result.needs_clarification is False


@pytest.mark.anyio
async def test_ambiguous_time_expression_is_not_guessed() -> None:
    result = await _recognize(
        '前三天有什么任务',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            confidence=1,
            time_scope=TimeScope.CUSTOM,
            raw_time_expression='前三天',
            clarification_reason=(
                ClarificationReason.AMBIGUOUS_TIME_EXPRESSION
            ),
        ),
    )

    assert result.query is not None
    assert result.query.start_at is None
    assert result.query.end_at is None
    assert result.query.raw_time_expression == '前三天'
    assert result.needs_clarification is True
    assert (
        result.clarification_reason
        == ClarificationReason.AMBIGUOUS_TIME_EXPRESSION
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    'time_scope',
    [TimeScope.TOMORROW, TimeScope.THIS_WEEK, TimeScope.OVERDUE],
)
async def test_fixed_time_scopes_remain_complete(
    time_scope: TimeScope,
) -> None:
    result = await _recognize(
        '固定时间查询',
        FakeIntentClassifier(
            intent=IntentType.QUERY_TASKS,
            time_scope=time_scope,
        ),
    )

    assert result.query is not None
    assert result.query.time_scope == time_scope
    assert result.query.start_at is None
    assert result.query.end_at is None
    assert result.needs_clarification is False
