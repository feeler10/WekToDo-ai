from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.intent.enums import IntentType, TimeScope
from app.intent.models import IntentResult, TaskQueryIntent
from app.schemas.task import TaskPriority, TaskQuery, TaskStatus


class TaskQueryPlanError(ValueError):
    """Base error for a query that cannot safely become executable."""


class IncompleteTaskQueryError(TaskQueryPlanError):
    """Raised when required query semantics are still unspecified."""


class InvalidTaskQueryTimeRangeError(TaskQueryPlanError):
    """Raised when an executable time boundary is missing or invalid."""


class TaskQueryPlan(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    user_id: str = Field(min_length=1)
    time_scope: TimeScope
    task_reference: str | None = None
    statuses: set[TaskStatus] | None = None
    priorities: set[TaskPriority] | None = None
    due_from: AwareDatetime | None = None
    due_to: AwareDatetime | None = None
    overdue_before: AwareDatetime | None = None

    @model_validator(mode='after')
    def validate_scope_boundaries(self) -> 'TaskQueryPlan':
        bounded_scopes = {
            TimeScope.TODAY,
            TimeScope.TOMORROW,
            TimeScope.THIS_WEEK,
            TimeScope.CUSTOM,
        }
        if self.time_scope in bounded_scopes:
            if self.due_from is None or self.due_to is None:
                raise ValueError('bounded time scopes require due_from and due_to')
            if self.due_from >= self.due_to:
                raise ValueError('due_from must be earlier than due_to')
            if self.overdue_before is not None:
                raise ValueError('bounded time scopes cannot be overdue queries')
        elif self.time_scope == TimeScope.ALL:
            if any(
                boundary is not None
                for boundary in (self.due_from, self.due_to, self.overdue_before)
            ):
                raise ValueError('ALL cannot carry time boundaries')
        elif self.time_scope == TimeScope.OVERDUE:
            if self.overdue_before is None:
                raise ValueError('OVERDUE requires overdue_before')
            if self.due_from is not None or self.due_to is not None:
                raise ValueError('OVERDUE cannot carry a normal time range')
        else:
            raise ValueError('UNSPECIFIED is not an executable time scope')
        return self


def build_task_query_plan(
    *,
    intent_result: IntentResult,
    user_id: str,
    timezone_name: str,
    now: datetime,
) -> TaskQueryPlan:
    if intent_result.intent != IntentType.QUERY_TASKS:
        raise TaskQueryPlanError('Task query plan requires QUERY_TASKS intent')
    if intent_result.needs_clarification:
        raise IncompleteTaskQueryError('Clarified query conditions are required')
    query = intent_result.query
    if query is None:
        raise IncompleteTaskQueryError('Task query intent is missing')
    if not user_id:
        raise TaskQueryPlanError('user_id must not be empty')
    _require_aware(now, field_name='now')

    scope = query.time_scope
    common = {
        'user_id': user_id,
        'time_scope': scope,
        'task_reference': intent_result.task_reference,
        'statuses': query.statuses,
        'priorities': query.priorities,
    }
    if scope == TimeScope.UNSPECIFIED:
        raise IncompleteTaskQueryError(
            'UNSPECIFIED cannot be converted into an executable query plan'
        )
    if scope == TimeScope.ALL:
        return TaskQueryPlan(**common)
    if scope == TimeScope.OVERDUE:
        return TaskQueryPlan(**common, overdue_before=now)
    if scope == TimeScope.CUSTOM:
        start_at, end_at = _validate_custom_range(query)
        return TaskQueryPlan(
            **common,
            due_from=start_at,
            due_to=end_at,
        )

    zone = _business_zone(timezone_name)
    local_date = now.astimezone(zone).date()
    if scope == TimeScope.TODAY:
        start_date = local_date
        end_date = local_date + timedelta(days=1)
    elif scope == TimeScope.TOMORROW:
        start_date = local_date + timedelta(days=1)
        end_date = local_date + timedelta(days=2)
    elif scope == TimeScope.THIS_WEEK:
        start_date = local_date - timedelta(days=local_date.weekday())
        end_date = start_date + timedelta(days=7)
    else:
        raise TaskQueryPlanError(f'Unsupported time scope: {scope}')

    return TaskQueryPlan(
        **common,
        due_from=_local_midnight(start_date, zone),
        due_to=_local_midnight(end_date, zone),
    )


def task_query_from_plan(
    plan: TaskQueryPlan,
    *,
    offset: int = 0,
    limit: int = 100,
) -> TaskQuery:
    return TaskQuery(
        user_id=plan.user_id,
        statuses=plan.statuses,
        priorities=plan.priorities,
        deadline_from=plan.due_from,
        deadline_to=plan.due_to,
        overdue_before=plan.overdue_before,
        offset=offset,
        limit=limit,
    )


def _validate_custom_range(
    query: TaskQueryIntent,
) -> tuple[datetime, datetime]:
    if query.start_at is None:
        raise InvalidTaskQueryTimeRangeError('CUSTOM requires start_at')
    if query.end_at is None:
        raise InvalidTaskQueryTimeRangeError('CUSTOM requires end_at')
    _require_aware(query.start_at, field_name='start_at')
    _require_aware(query.end_at, field_name='end_at')
    if query.start_at >= query.end_at:
        raise InvalidTaskQueryTimeRangeError(
            'CUSTOM requires start_at earlier than end_at'
        )
    return query.start_at, query.end_at


def _require_aware(value: datetime, *, field_name: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None or value.utcoffset() is None
    ):
        raise InvalidTaskQueryTimeRangeError(
            f'{field_name} must include timezone information'
        )


def _business_zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TaskQueryPlanError(
            f'Unknown business timezone: {timezone_name}'
        ) from exc


def _local_midnight(value: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(value, time.min, tzinfo=zone)
