from app.schemas.task import TaskPriority, TaskUpdate
from app.schemas.task_attribute_update import (
    TaskFieldName,
    TaskFieldOperation,
    TaskUpdateParseResult,
)


def build_task_update(
    result: TaskUpdateParseResult,
    *,
    user_id: str,
    expected_version: int,
) -> TaskUpdate:
    values: dict[str, object] = {}
    for change in result.changes:
        field = change.field
        if change.operation == TaskFieldOperation.CLEAR:
            values[field.value] = (
                '' if field == TaskFieldName.DESCRIPTION else None
            )
            continue
        value = change.value
        if field == TaskFieldName.USER_PRIORITY:
            value = TaskPriority(value)
        values[field.value] = value
    return TaskUpdate(
        user_id=user_id,
        expected_version=expected_version,
        **values,
    )
