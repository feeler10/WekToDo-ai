from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.intent.enums import IntentType, TimeScope
from app.intent.models import IntentResult, TaskQueryIntent
from app.schemas.task import TaskPriority, TaskStatus
from app.services.task_query_plan import (
    IncompleteTaskQueryError,
    InvalidTaskQueryTimeRangeError,
    build_task_query_plan,
    task_query_from_plan,
)


NOW = datetime(2026, 8, 2, 15, 30, tzinfo=timezone.utc)
SHANGHAI = ZoneInfo('Asia/Shanghai')


def _result(
    scope: TimeScope,
    **query_values: object,
) -> IntentResult:
    return IntentResult(
        intent=IntentType.QUERY_TASKS,
        confidence=1,
        reason='test query',
        query=TaskQueryIntent(time_scope=scope, **query_values),
    )


def _build(result: IntentResult):
    return build_task_query_plan(
        intent_result=result,
        user_id='user-1',
        timezone_name='Asia/Shanghai',
        now=NOW,
    )


@pytest.mark.parametrize(
    ('scope', 'expected_start', 'expected_end'),
    [
        (
            TimeScope.TODAY,
            datetime(2026, 8, 2, tzinfo=SHANGHAI),
            datetime(2026, 8, 3, tzinfo=SHANGHAI),
        ),
        (
            TimeScope.TOMORROW,
            datetime(2026, 8, 3, tzinfo=SHANGHAI),
            datetime(2026, 8, 4, tzinfo=SHANGHAI),
        ),
        (
            TimeScope.THIS_WEEK,
            datetime(2026, 7, 27, tzinfo=SHANGHAI),
            datetime(2026, 8, 3, tzinfo=SHANGHAI),
        ),
    ],
)
def test_fixed_scopes_build_business_timezone_half_open_ranges(
    scope: TimeScope,
    expected_start: datetime,
    expected_end: datetime,
) -> None:
    plan = _build(_result(scope, raw_time_expression='diagnostic only'))

    assert plan.due_from == expected_start
    assert plan.due_to == expected_end
    assert plan.overdue_before is None
    assert plan.due_from is not None and plan.due_from.utcoffset() is not None
    assert plan.due_to is not None and plan.due_to.utcoffset() is not None


def test_custom_maps_validated_boundaries_without_reparsing_raw_expression() -> None:
    start = datetime(2026, 7, 31, tzinfo=SHANGHAI)
    end = datetime(2026, 8, 1, tzinfo=SHANGHAI)
    result = _result(
        TimeScope.CUSTOM,
        start_at=start,
        end_at=end,
        raw_time_expression='即使这里写成未来三天也不得重算',
        statuses={TaskStatus.DOING},
        priorities={TaskPriority.HIGH},
    )

    plan = _build(result)

    assert plan.due_from is start
    assert plan.due_to is end
    assert plan.statuses == {TaskStatus.DOING}
    assert plan.priorities == {TaskPriority.HIGH}


@pytest.mark.parametrize(
    ('start_at', 'end_at', 'message'),
    [
        (
            None,
            datetime(2026, 8, 2, tzinfo=timezone.utc),
            'requires start_at',
        ),
        (
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            None,
            'requires end_at',
        ),
        (
            datetime(2026, 8, 1),
            datetime(2026, 8, 2, tzinfo=timezone.utc),
            'start_at must include timezone',
        ),
        (
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 2),
            'end_at must include timezone',
        ),
        (
            datetime(2026, 8, 2, tzinfo=timezone.utc),
            datetime(2026, 8, 2, tzinfo=timezone.utc),
            'earlier than end_at',
        ),
        (
            datetime(2026, 8, 3, tzinfo=timezone.utc),
            datetime(2026, 8, 2, tzinfo=timezone.utc),
            'earlier than end_at',
        ),
    ],
)
def test_custom_defensive_boundary_rejects_invalid_constructed_intent(
    start_at: datetime | None,
    end_at: datetime | None,
    message: str,
) -> None:
    query = TaskQueryIntent.model_construct(
        time_scope=TimeScope.CUSTOM,
        start_at=start_at,
        end_at=end_at,
        statuses=None,
        priorities=None,
        raw_time_expression='invalid test input',
    )
    result = IntentResult.model_construct(
        intent=IntentType.QUERY_TASKS,
        confidence=1,
        reason='defensive test',
        task_reference=None,
        target_status=None,
        query=query,
        needs_clarification=False,
        clarification_reason=None,
        clarification_question=None,
    )

    with pytest.raises(InvalidTaskQueryTimeRangeError, match=message):
        _build(result)


def test_all_has_no_time_restriction() -> None:
    plan = _build(_result(TimeScope.ALL))

    assert plan.due_from is None
    assert plan.due_to is None
    assert plan.overdue_before is None


def test_unspecified_fails_closed() -> None:
    with pytest.raises(IncompleteTaskQueryError, match='UNSPECIFIED'):
        _build(_result(TimeScope.UNSPECIFIED))


def test_overdue_uses_strict_now_boundary_and_preserves_filters() -> None:
    plan = _build(
        _result(
            TimeScope.OVERDUE,
            statuses={TaskStatus.DOING},
        )
    )

    assert plan.overdue_before is NOW
    assert plan.due_from is None
    assert plan.due_to is None
    assert plan.statuses == {TaskStatus.DOING}


def test_plan_converts_to_existing_repository_deadline_contract() -> None:
    plan = _build(
        _result(
            TimeScope.TODAY,
            statuses={TaskStatus.TODO},
            priorities={TaskPriority.URGENT},
        )
    )

    query = task_query_from_plan(plan)

    assert query.user_id == 'user-1'
    assert query.deadline_from == plan.due_from
    assert query.deadline_to == plan.due_to
    assert query.overdue_before is None
    assert query.statuses == {TaskStatus.TODO}
    assert query.priorities == {TaskPriority.URGENT}


def test_dst_transition_uses_local_date_boundaries_not_fixed_24_hours() -> None:
    new_york = ZoneInfo('America/New_York')
    now = datetime(2026, 3, 8, 12, tzinfo=timezone.utc)
    plan = build_task_query_plan(
        intent_result=_result(TimeScope.TODAY),
        user_id='user-1',
        timezone_name='America/New_York',
        now=now,
    )

    assert plan.due_from == datetime(2026, 3, 8, tzinfo=new_york)
    assert plan.due_to == datetime(2026, 3, 9, tzinfo=new_york)
    assert plan.due_from is not None and plan.due_to is not None
    assert (
        plan.due_to.astimezone(timezone.utc)
        - plan.due_from.astimezone(timezone.utc)
    ) == timedelta(hours=23)
