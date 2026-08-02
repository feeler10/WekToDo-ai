import re
from dataclasses import dataclass

from app.schemas.task import TaskPriority, TaskStatus
from app.schemas.task_operation import TaskQueryKind, TaskReferenceUpdate


@dataclass(frozen=True)
class ParsedTaskQuery:
    kind: TaskQueryKind
    reference: str | None = None
    statuses: set[TaskStatus] | None = None
    priorities: set[TaskPriority] | None = None


def parse_task_query(message: str) -> ParsedTaskQuery:
    normalized = message.strip()
    if '逾期' in normalized:
        return ParsedTaskQuery(TaskQueryKind.OVERDUE)
    if '今天' in normalized or '今日' in normalized:
        return ParsedTaskQuery(TaskQueryKind.TODAY)
    if '详情' in normalized or '详细信息' in normalized:
        reference = re.sub(r'^(查看|查询)\s*', '', normalized)
        reference = re.sub(
            r'(的)?(详情|详细信息)[？?。]?$',
            '',
            reference,
        )
        return ParsedTaskQuery(TaskQueryKind.DETAIL, reference=reference.strip())

    statuses: set[TaskStatus] | None = None
    if '未完成' in normalized:
        statuses = {TaskStatus.TODO, TaskStatus.DOING, TaskStatus.BLOCKED}
    elif '已完成' in normalized:
        statuses = {TaskStatus.DONE}

    priorities: set[TaskPriority] | None = None
    if '高优先级' in normalized:
        priorities = {TaskPriority.HIGH, TaskPriority.URGENT}
    return ParsedTaskQuery(
        TaskQueryKind.LIST,
        statuses=statuses,
        priorities=priorities,
    )


def parse_status_update(message: str) -> TaskReferenceUpdate:
    normalized = message.strip().rstrip('。！？!?')
    status_patterns = (
        (TaskStatus.DONE, r'(已经|已)?(完成|做完)(了)?$|标记为(已)?完成$'),
        (TaskStatus.BLOCKED, r'标记为阻塞$|变成阻塞$|阻塞了?$'),
        (TaskStatus.CANCELLED, r'标记为取消$|取消了?$'),
        (TaskStatus.DOING, r'标记为进行中$|开始(做|处理)?了?$|重新开始$'),
        (TaskStatus.TODO, r'标记为待办$|改回待办$'),
    )
    target: TaskStatus | None = None
    reference = normalized
    for status, pattern in status_patterns:
        match = re.search(pattern, normalized)
        if match:
            target = status
            reference = normalized[: match.start()]
            break
    if target is None:
        raise ValueError('Could not determine target task status')

    reference = re.sub(r'^(把|将)\s*', '', reference)
    reference = re.sub(r'(的状态|状态)\s*$', '', reference)
    reference = reference.strip(' ，,：:')
    if not reference:
        raise ValueError('Could not determine task reference')
    return TaskReferenceUpdate(reference=reference, target_status=target)
