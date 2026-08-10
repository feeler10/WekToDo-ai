from datetime import datetime, timedelta, timezone

from app.intent.models import IntentRecognitionContext
from app.intent.prompts import build_intent_messages


def test_prompt_covers_structured_query_and_write_boundaries() -> None:
    messages = build_intent_messages(
        IntentRecognitionContext(message='论文做完了吗')
    )
    system = messages[0][1]

    assert 'query.time_scope=TODAY' in system
    assert 'query.time_scope=UNSPECIFIED' in system
    assert 'query.time_scope=ALL' in system
    assert 'query.statuses=[TODO,DOING,BLOCKED]' in system
    assert '论文做完了吗' in system
    assert 'target_status=null' in system
    assert '论文做完了' in system
    assert 'target_status=DONE' in system
    assert 'MISSING_TASK_REFERENCE' in system


def test_prompt_injects_time_context_and_custom_range_contract() -> None:
    current = datetime(
        2026,
        8,
        2,
        23,
        30,
        tzinfo=timezone(timedelta(hours=8)),
    )
    messages = build_intent_messages(
        IntentRecognitionContext(
            message='未来三天有哪些任务',
            current_datetime=current,
            business_timezone='Asia/Shanghai',
            week_starts_on='Monday',
        )
    )
    system = messages[0][1]

    assert 'Current datetime: 2026-08-02T23:30:00+08:00' in system
    assert 'Business timezone: Asia/Shanghai' in system
    assert 'Week starts on: Monday' in system
    assert '昨天的昨天有什么规划' in system
    assert '未来三天有哪些未完成任务' in system
    assert '最近五天有哪些任务' in system
    assert '最近/近 N 天' in system
    assert '今年 8 月 5 日到 8 月 10 日有哪些任务' in system
    assert '明天下午有什么任务' in system
    assert 'raw_time_expression' in system
    assert 'start_at <= due_at < end_at' in system
    assert 'AMBIGUOUS_TIME_EXPRESSION' in system
    assert 'INVALID_TIME_RANGE' in system
