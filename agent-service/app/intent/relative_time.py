import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.intent.enums import IntentType, TimeScope
from app.intent.models import (
    IntentRecognitionContext,
    IntentResult,
    TaskQueryIntent,
)

_UPCOMING_DAYS_PATTERN = re.compile(
    r'(?<!过去)(?P<expression>(?:最近|近)\s*'
    r'(?P<count>\d{1,3}|[一二两三四五六七八九十百]+)\s*天)'
)
_CHINESE_DIGITS = {
    '一': 1,
    '二': 2,
    '两': 2,
    '三': 3,
    '四': 4,
    '五': 5,
    '六': 6,
    '七': 7,
    '八': 8,
    '九': 9,
}


def normalize_upcoming_day_range(
    result: IntentResult,
    context: IntentRecognitionContext,
) -> IntentResult:
    """Apply the product meaning of recent N days to task queries.

    The range contains today and spans N local calendar days. This narrow
    deterministic correction prevents an LLM from using a look-back range
    while leaving all other custom expressions unchanged.
    """
    if result.intent != IntentType.QUERY_TASKS:
        return result

    match = _UPCOMING_DAYS_PATTERN.search(context.message)
    if match is None:
        return result

    day_count = _parse_day_count(match.group('count'))
    if day_count is None or not 1 <= day_count <= 365:
        return result

    business_timezone = ZoneInfo(context.business_timezone)
    local_today = context.current_datetime.astimezone(business_timezone).date()
    start_at = datetime.combine(local_today, time.min, tzinfo=business_timezone)
    end_at = datetime.combine(
        local_today + timedelta(days=day_count),
        time.min,
        tzinfo=business_timezone,
    )
    existing_query = result.query or TaskQueryIntent()
    query = existing_query.model_copy(
        update={
            'time_scope': TimeScope.CUSTOM,
            'start_at': start_at,
            'end_at': end_at,
            'raw_time_expression': match.group('expression').replace(' ', ''),
        }
    )
    return result.model_copy(
        update={
            'query': query,
            'needs_clarification': False,
            'clarification_reason': None,
            'clarification_question': None,
        }
    )


def _parse_day_count(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    if value == '十':
        return 10
    if value == '百':
        return 100
    if '百' in value:
        hundreds, remainder = value.split('百', maxsplit=1)
        hundreds_value = _CHINESE_DIGITS.get(hundreds)
        remainder_value = _parse_day_count(remainder) if remainder else 0
        if hundreds_value is None or remainder_value is None:
            return None
        return hundreds_value * 100 + remainder_value
    if '十' in value:
        tens, units = value.split('十', maxsplit=1)
        tens_value = _CHINESE_DIGITS.get(tens, 1) if tens else 1
        units_value = _CHINESE_DIGITS.get(units, 0) if units else 0
        return tens_value * 10 + units_value
    return _CHINESE_DIGITS.get(value)
