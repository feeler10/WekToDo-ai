from collections.abc import Sequence

from app.schemas.draft import TaskDraftCandidate, TaskDraftFieldName
from app.services.pending_operation import (
    format_pending_operation_inputs,
    is_pending_operation_cancellation,
    looks_like_explicit_new_operation,
)


_CREATE_CANCELLATION_MESSAGES = {
    '取消创建',
    '不创建了',
    '不建了',
}
_FIELD_LABELS = {
    TaskDraftFieldName.TITLE: '任务名称',
    TaskDraftFieldName.DESCRIPTION: '任务描述',
    TaskDraftFieldName.CATEGORY: '任务分类',
    TaskDraftFieldName.DEADLINE: '截止时间',
    TaskDraftFieldName.ESTIMATED_MINUTES: '预计耗时',
}


def missing_task_draft_fields(
    candidate: TaskDraftCandidate,
) -> list[TaskDraftFieldName]:
    missing = list(candidate.missing_fields)
    if candidate.title is None and TaskDraftFieldName.TITLE not in missing:
        missing.insert(0, TaskDraftFieldName.TITLE)
    return list(dict.fromkeys(missing))


def format_task_draft_clarification(
    candidate: TaskDraftCandidate,
    missing_fields: Sequence[TaskDraftFieldName],
) -> str:
    if candidate.clarification_question:
        return candidate.clarification_question
    if list(missing_fields) == [TaskDraftFieldName.TITLE]:
        return '这个任务叫什么？请告诉我一个明确的任务名称。'
    labels = '、'.join(_FIELD_LABELS[field] for field in missing_fields)
    return f'还需要确认以下信息：{labels}。请补充或修正。'


def format_task_collection_input(user_inputs: Sequence[str]) -> str:
    return format_pending_operation_inputs(
        user_inputs,
        operation_label='待创建任务',
    )


def is_task_draft_collection_cancellation(message: str) -> bool:
    return is_pending_operation_cancellation(
        message,
        additional_messages=_CREATE_CANCELLATION_MESSAGES,
    )


def looks_like_explicit_new_request(message: str) -> bool:
    return looks_like_explicit_new_operation(
        message,
        replacement_prefixes=('创建另一个', '新建另一个', '重新创建'),
    )
