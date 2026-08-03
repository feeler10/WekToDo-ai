import re
from collections.abc import Mapping, Sequence

from app.matching.keyword import normalize_task_reference
from app.schemas.query_context import PendingTaskSelection
from app.schemas.task import Task


_CANCEL_MESSAGES = {'取消', '算了', '不用了', '不用查了', '不查了'}
_NEW_REQUEST_MARKERS = (
    '创建',
    '新建',
    '查看',
    '查询',
    '有哪些',
    '什么任务',
    '标记',
    '完成',
    '取消任务',
    '拆解',
)
_ORDINAL_PATTERN = re.compile(r'^第?([一二三四五六七八九十]|\d+)(?:个|项|条)?$')
_CHINESE_ORDINALS = {
    '一': 1,
    '二': 2,
    '三': 3,
    '四': 4,
    '五': 5,
    '六': 6,
    '七': 7,
    '八': 8,
    '九': 9,
    '十': 10,
}


class TaskSelectionError(ValueError):
    pass


class AmbiguousTaskSelectionError(TaskSelectionError):
    pass


def is_pending_cancellation(message: str) -> bool:
    normalized = re.sub(r'[\s，,。！？!?]', '', message)
    return normalized in _CANCEL_MESSAGES


def looks_like_new_request(message: str) -> bool:
    return any(marker in message for marker in _NEW_REQUEST_MARKERS)


def parse_candidate_selection(
    *,
    message: str,
    pending: PendingTaskSelection,
    tasks_by_id: Mapping[str, Task],
) -> str:
    normalized_message = message.strip()
    ordinal = _parse_ordinal(normalized_message)
    if ordinal is not None:
        if ordinal < 1 or ordinal > len(pending.candidate_task_ids):
            raise TaskSelectionError('这个序号不在候选范围内。')
        return pending.candidate_task_ids[ordinal - 1]

    if normalized_message in pending.candidate_task_ids:
        return normalized_message

    available = [
        tasks_by_id[task_id]
        for task_id in pending.candidate_task_ids
        if task_id in tasks_by_id
    ]
    exact = [task for task in available if task.title.strip() == normalized_message]
    if len(exact) == 1:
        return exact[0].id
    if len(exact) > 1:
        raise AmbiguousTaskSelectionError(
            '这个标题仍对应多个候选任务。'
        )

    normalized_title = normalize_task_reference(normalized_message)
    normalized = [
        task
        for task in available
        if normalize_task_reference(task.title) == normalized_title
    ]
    if len(normalized) == 1:
        return normalized[0].id
    if len(normalized) > 1:
        raise AmbiguousTaskSelectionError(
            '规范化后的标题仍对应多个候选任务。'
        )
    raise TaskSelectionError('没有在当前候选中找到你的选择。')


def ordered_available_tasks(
    pending: PendingTaskSelection,
    tasks_by_id: Mapping[str, Task],
) -> list[Task]:
    return [
        tasks_by_id[task_id]
        for task_id in pending.candidate_task_ids
        if task_id in tasks_by_id
    ]


def refreshed_pending_selection(
    pending: PendingTaskSelection,
    tasks: Sequence[Task],
) -> PendingTaskSelection:
    return pending.model_copy(
        update={
            'candidate_task_ids': [task.id for task in tasks],
            'candidate_versions': {
                task.id: task.version for task in tasks
            },
        }
    )


def _parse_ordinal(message: str) -> int | None:
    match = _ORDINAL_PATTERN.fullmatch(message)
    if match is None:
        return None
    value = match.group(1)
    return int(value) if value.isdigit() else _CHINESE_ORDINALS[value]
