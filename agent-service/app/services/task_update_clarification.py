from collections.abc import Sequence

from app.services.pending_operation import (
    format_pending_operation_inputs,
    is_pending_operation_cancellation,
    looks_like_explicit_new_operation,
)


_UPDATE_CANCELLATION_MESSAGES = {
    '取消修改',
    '不修改了',
    '不改了',
}


def format_task_update_collection_input(user_inputs: Sequence[str]) -> str:
    return format_pending_operation_inputs(
        user_inputs,
        operation_label='待修改任务',
    )


def is_task_update_collection_cancellation(message: str) -> bool:
    return is_pending_operation_cancellation(
        message,
        additional_messages=_UPDATE_CANCELLATION_MESSAGES,
    )


def looks_like_explicit_new_request(message: str) -> bool:
    return looks_like_explicit_new_operation(
        message,
        replacement_prefixes=(
            '创建一个',
            '新建一个',
            '创建另一个',
            '新建另一个',
            '修改另一个',
            '改另一个',
        ),
    )
