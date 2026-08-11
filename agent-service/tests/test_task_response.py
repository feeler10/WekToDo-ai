from datetime import datetime, timezone

from app.intent.enums import TimeScope
from app.schemas.task import Task, TaskPriority, TaskStatus
from app.services.task_query_plan import TaskQueryPlan
from app.services.task_response import (
    format_multiple_matches_response,
    format_subtask_list_response,
    format_task_detail_response,
    format_task_list_response,
    format_zero_match_response,
)


def _plan(scope: TimeScope, **kwargs) -> TaskQueryPlan:
    values = {'user_id': 'user-1', 'time_scope': scope, **kwargs}
    if scope in {
        TimeScope.TODAY,
        TimeScope.TOMORROW,
        TimeScope.THIS_WEEK,
        TimeScope.CUSTOM,
    }:
        values.setdefault(
            'due_from',
            datetime.fromisoformat('2026-08-03T00:00:00+08:00'),
        )
        values.setdefault(
            'due_to',
            datetime.fromisoformat('2026-08-04T00:00:00+08:00'),
        )
    if scope == TimeScope.OVERDUE:
        values['overdue_before'] = datetime(2026, 8, 3, tzinfo=timezone.utc)
    return TaskQueryPlan.model_validate(values)


def test_zero_match_uses_real_scope_context() -> None:
    assert format_zero_match_response(plan=_plan(TimeScope.TODAY)) == (
        '今天没有符合条件的任务。'
    )
    assert format_zero_match_response(plan=_plan(TimeScope.ALL)) == (
        '没有找到符合条件的任务。'
    )
    assert format_zero_match_response(
        plan=None,
        reference='吃饭',
    ) == '没有找到与“吃饭”匹配的任务。'


def test_detail_converts_deadline_and_omits_missing_values() -> None:
    with_deadline = Task(
        id='one',
        user_id='user-1',
        title='论文实验',
        status=TaskStatus.DOING,
        deadline=datetime(2026, 8, 3, 10, tzinfo=timezone.utc),
        ai_priority=TaskPriority.HIGH,
    )
    without_deadline = Task(
        id='two',
        user_id='user-1',
        title='整理材料',
    )

    detail = format_task_detail_response(
        with_deadline,
        timezone_name='Asia/Shanghai',
    )
    plain = format_task_detail_response(
        without_deadline,
        timezone_name='Asia/Shanghai',
    )

    assert '进行中' in detail
    assert '8 月 3 日 18:00' in detail
    assert '高' in detail
    assert '截止时间' not in plain
    assert 'None' not in plain
    assert 'null' not in plain


def test_today_list_counts_tasks_and_high_priorities_from_array() -> None:
    tasks = [
        Task(
            id='one',
            user_id='user-1',
            title='高优先级',
            status=TaskStatus.DOING,
            ai_priority=TaskPriority.HIGH,
        ),
        Task(
            id='two',
            user_id='user-1',
            title='普通任务',
            status=TaskStatus.BLOCKED,
            ai_priority=TaskPriority.MEDIUM,
        ),
    ]
    plan = _plan(
        TimeScope.TODAY,
        statuses={
            TaskStatus.TODO,
            TaskStatus.DOING,
            TaskStatus.BLOCKED,
        },
    )

    response = format_task_list_response(
        tasks,
        plan=plan,
        timezone_name='Asia/Shanghai',
    )

    assert '今天还有 2 个未完成任务' in response
    assert '其中 1 个为高优先级' in response
    assert response.index('1. 高优先级') < response.index('2. 普通任务')


def test_custom_all_and_overdue_have_distinct_copy() -> None:
    task = Task(id='one', user_id='user-1', title='任务')

    custom = format_task_list_response(
        [task],
        plan=_plan(TimeScope.CUSTOM),
        timezone_name='Asia/Shanghai',
    )
    all_time = format_task_list_response(
        [task],
        plan=_plan(TimeScope.ALL),
        timezone_name='Asia/Shanghai',
    )
    overdue = format_task_list_response(
        [task],
        plan=_plan(TimeScope.OVERDUE),
        timezone_name='Asia/Shanghai',
    )

    assert '共找到 1 个' in custom
    assert '共找到 1 个' in all_time
    assert '未完成的逾期任务' in overdue


def test_multiple_candidates_preserve_input_order() -> None:
    tasks = [
        Task(id='two', user_id='user-1', title='论文修改'),
        Task(id='one', user_id='user-1', title='论文实验'),
    ]

    response = format_multiple_matches_response(
        reference='论文',
        tasks=tasks,
        timezone_name='Asia/Shanghai',
        operation_label='查看',
    )

    assert response.index('1. 论文修改') < response.index('2. 论文实验')


def test_list_groups_children_under_parent_in_chat_copy() -> None:
    parent = Task(
        id='parent',
        user_id='user-1',
        title='完成扩散模型论文实验',
        ai_priority=TaskPriority.URGENT,
    )
    children = [
        Task(
            id='child-1',
            user_id='user-1',
            parent_id='parent',
            title='准备数据集',
            subtask_order=1,
        ),
        Task(
            id='child-2',
            user_id='user-1',
            parent_id='parent',
            title='运行模型训练',
            subtask_order=2,
            ai_priority=TaskPriority.HIGH,
        ),
    ]
    standalone = Task(
        id='standalone',
        user_id='user-1',
        title='接水',
    )

    response = format_task_list_response(
        [*children, parent, standalone],
        plan=_plan(TimeScope.ALL),
        timezone_name='Asia/Shanghai',
    )

    assert '共找到 2 个符合条件的任务' in response
    assert '其中 1 个为高优先级' in response
    assert '完成扩散模型论文实验（含 2 个子任务）' in response
    assert '准备数据集' not in response
    assert '运行模型训练' not in response


def test_explicit_subtask_query_returns_ordered_real_children() -> None:
    parent = Task(id='parent', user_id='user-1', title='论文实验')
    subtasks = [
        Task(
            id='second',
            user_id='user-1',
            parent_id='parent',
            title='运行实验',
            subtask_order=2,
        ),
        Task(
            id='first',
            user_id='user-1',
            parent_id='parent',
            title='准备数据',
            subtask_order=1,
        ),
    ]

    response = format_subtask_list_response(
        parent,
        subtasks,
        timezone_name='Asia/Shanghai',
    )

    assert '“论文实验”共有 2 个子任务' in response
    assert response.index('1. 准备数据') < response.index('2. 运行实验')


def test_filtered_child_result_is_summarized_by_stored_parent() -> None:
    parent = Task(id='parent', user_id='user-1', title='论文实验')
    matching_child = Task(
        id='matching',
        user_id='user-1',
        parent_id='parent',
        title='今天运行实验',
        subtask_order=1,
    )
    other_child = Task(
        id='other',
        user_id='user-1',
        parent_id='parent',
        title='明天整理结果',
        subtask_order=2,
    )

    response = format_task_list_response(
        [matching_child],
        plan=_plan(TimeScope.TODAY),
        timezone_name='Asia/Shanghai',
        all_tasks=[parent, matching_child, other_child],
    )

    assert '今天有 1 个符合条件的任务' in response
    assert '论文实验（含 2 个子任务）' in response
    assert '今天运行实验' not in response
