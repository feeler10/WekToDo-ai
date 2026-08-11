from collections import Counter
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from app.intent.enums import ClarificationReason, TimeScope
from app.schemas.task import Task, TaskPriority, TaskStatus, TaskUpdate
from app.services.task_query_plan import TaskQueryPlan


STATUS_LABELS: dict[TaskStatus, str] = {
    TaskStatus.TODO: '待办',
    TaskStatus.DOING: '进行中',
    TaskStatus.BLOCKED: '已阻塞',
    TaskStatus.DONE: '已完成',
    TaskStatus.CANCELLED: '已取消',
}

PRIORITY_LABELS: dict[TaskPriority, str] = {
    TaskPriority.LOW: '低',
    TaskPriority.MEDIUM: '中',
    TaskPriority.HIGH: '高',
    TaskPriority.URGENT: '紧急',
}

_OPEN_STATUSES = {
    TaskStatus.TODO,
    TaskStatus.DOING,
    TaskStatus.BLOCKED,
}
_HIGH_PRIORITIES = {TaskPriority.HIGH, TaskPriority.URGENT}


def format_task_list_response(
    tasks: list[Task],
    *,
    plan: TaskQueryPlan | None,
    timezone_name: str,
    all_tasks: list[Task] | None = None,
) -> str:
    if not tasks:
        return format_zero_match_response(plan=plan)

    hierarchy_tasks = all_tasks if all_tasks is not None else tasks
    child_counts = Counter(
        task.parent_id
        for task in hierarchy_tasks
        if task.parent_id is not None
    )
    tasks_by_id = {task.id: task for task in hierarchy_tasks}
    root_tasks = _unique_tasks(
        tasks_by_id.get(task.parent_id) if task.parent_id else task
        for task in tasks
    )
    if not root_tasks:
        return format_zero_match_response(plan=plan)

    count = len(root_tasks)
    high_count = sum(
        task.effective_priority in _HIGH_PRIORITIES for task in root_tasks
    )
    unfinished = bool(plan and plan.statuses == _OPEN_STATUSES)
    scope = plan.time_scope if plan is not None else None
    if scope == TimeScope.TODAY:
        header = (
            f'今天还有 {count} 个未完成任务'
            if unfinished
            else f'今天有 {count} 个符合条件的任务'
        )
    elif scope == TimeScope.TOMORROW:
        header = f'明天有 {count} 个符合条件的任务'
    elif scope == TimeScope.THIS_WEEK:
        header = f'本周有 {count} 个符合条件的任务'
    elif scope == TimeScope.OVERDUE:
        header = f'有 {count} 个未完成的逾期任务'
    else:
        header = f'共找到 {count} 个符合条件的任务'
    if high_count:
        header += f'，其中 {high_count} 个为高优先级'
    lines = [f'{header}。', '']
    lines.extend(
        f'{index}. '
        f'{_format_task_line(task, timezone_name, child_count=child_counts[task.id])}'
        for index, task in enumerate(root_tasks, start=1)
    )
    return '\n'.join(lines)


def _unique_tasks(tasks: Iterable[Task | None]) -> list[Task]:
    result: list[Task] = []
    seen: set[str] = set()
    for task in tasks:
        if task is None or task.id in seen:
            continue
        result.append(task)
        seen.add(task.id)
    return result


def format_subtask_list_response(
    parent: Task,
    subtasks: list[Task],
    *,
    timezone_name: str,
) -> str:
    ordered = sorted(
        subtasks,
        key=lambda task: (
            task.subtask_order if task.subtask_order is not None else 10**9,
            task.created_at,
            task.id,
        ),
    )
    if not ordered:
        return f'“{parent.title}”当前没有子任务。'
    lines = [f'“{parent.title}”共有 {len(ordered)} 个子任务：', '']
    lines.extend(
        f'{index}. {_format_task_line(task, timezone_name)}'
        for index, task in enumerate(ordered, start=1)
    )
    return '\n'.join(lines)


def format_task_detail_response(
    task: Task,
    *,
    timezone_name: str,
) -> str:
    facts = [f'当前状态为“{STATUS_LABELS[task.status]}”']
    if task.deadline is not None:
        facts.append(
            f'截止时间为 {_format_datetime(task.deadline, timezone_name)}'
        )
    if task.effective_priority is not None:
        facts.append(
            f'优先级为“{PRIORITY_LABELS[task.effective_priority]}”'
        )
    response = f'“{task.title}”' + '，'.join(facts) + '。'
    if task.status == TaskStatus.CANCELLED:
        response += ' 该任务已被取消；如需修改、更新状态或拆解，请先恢复为待办。'
    return response


def format_zero_match_response(
    *,
    plan: TaskQueryPlan | None,
    reference: str | None = None,
) -> str:
    if reference:
        return f'没有找到与“{reference}”匹配的任务。'
    if plan is not None and plan.time_scope == TimeScope.TODAY:
        return '今天没有符合条件的任务。'
    if plan is not None and plan.time_scope == TimeScope.OVERDUE:
        return '没有未完成的逾期任务。'
    return '没有找到符合条件的任务。'


def format_multiple_matches_response(
    *,
    reference: str,
    tasks: list[Task],
    timezone_name: str,
    operation_label: str,
) -> str:
    lines = [
        f'找到了多个与“{reference}”匹配的任务，'
        f'请选择你想{operation_label}的任务：',
        '',
    ]
    lines.extend(
        f'{index}. {_format_task_line(task, timezone_name)}'
        for index, task in enumerate(tasks, start=1)
    )
    return '\n'.join(lines)


def format_query_clarification(
    *,
    reason: ClarificationReason,
    question: str | None,
) -> str:
    if question:
        return question
    if reason == ClarificationReason.MISSING_TIME_SCOPE:
        return '你想查看哪个时间范围内的任务？例如今天、本周或者所有任务。'
    if reason == ClarificationReason.MISSING_TASK_REFERENCE:
        return '你指的是哪个任务？请告诉我任务名称。'
    return '请补充更明确的查询条件。'


def format_selection_error(message: str) -> str:
    return f'{message} 请从当前候选任务中重新选择。'


def format_cancelled_response(kind: str) -> str:
    return f'已取消本次{kind}。'


def format_stale_candidate_response() -> str:
    return '该候选任务已发生变化或已不存在，请重新发起请求。'


def format_status_update_result(task: Task) -> str:
    return f'已将“{task.title}”更新为“{STATUS_LABELS[task.status]}”。'


def format_task_update_preview(
    task: Task,
    update: TaskUpdate,
    *,
    timezone_name: str,
) -> str:
    labels = {
        'title': '标题',
        'description': '描述',
        'category': '分类',
        'deadline': '截止时间',
        'estimated_minutes': '预计耗时',
        'user_priority': '用户优先级',
    }
    changes = update.model_dump(
        exclude_unset=True,
        exclude={'user_id', 'expected_version'},
    )
    lines = [f'准备修改任务“{task.title}”：']
    for field, value in changes.items():
        old_value = getattr(task, field)
        lines.append(
            f'- {labels[field]}：{_format_update_value(field, old_value, timezone_name)}'
            f' → {_format_update_value(field, value, timezone_name)}'
        )
    lines.append('请确认是否执行。')
    return '\n'.join(lines)


def format_task_update_result(task: Task) -> str:
    return f'已更新任务“{task.title}”的属性。'


def _format_update_value(field: str, value: object, timezone_name: str) -> str:
    if value is None:
        return '未设置'
    if field == 'deadline':
        assert isinstance(value, datetime)
        return _format_datetime(value, timezone_name)
    if field == 'estimated_minutes':
        return f'{value} 分钟'
    if field == 'user_priority':
        priority = value if isinstance(value, TaskPriority) else TaskPriority(value)
        return PRIORITY_LABELS[priority]
    return str(value)


def _format_task_line(
    task: Task,
    timezone_name: str,
    *,
    child_count: int = 0,
) -> str:
    title = (
        f'{task.title}（含 {child_count} 个子任务）'
        if child_count
        else task.title
    )
    parts = [title, STATUS_LABELS[task.status]]
    if task.deadline is not None:
        parts.append(f'截止时间 {_format_datetime(task.deadline, timezone_name)}')
    if task.effective_priority is not None:
        parts.append(f'{PRIORITY_LABELS[task.effective_priority]}优先级')
    return '，'.join(parts)


def _format_datetime(value: datetime, timezone_name: str) -> str:
    local = value.astimezone(ZoneInfo(timezone_name))
    return f'{local.month} 月 {local.day} 日 {local:%H:%M}'
