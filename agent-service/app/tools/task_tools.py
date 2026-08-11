from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.repositories.base import TaskRepository
from app.schemas.task import (
    Task,
    TaskCreate,
    TaskListResponse,
    TaskQuery,
    TaskStatus,
    TaskUpdate,
    utc_now,
)
from app.schemas.subtask import (
    SubtaskBatchCreate,
    SubtaskBatchResult,
    TaskStatusUpdateResult,
)
from app.schemas.task_deletion import (
    TaskDelete,
    TaskDeleteBatch,
    TaskDeleteBatchResult,
    TaskDeleteResult,
)


_OPEN_STATUSES = {TaskStatus.TODO, TaskStatus.DOING, TaskStatus.BLOCKED}


async def create_task(
    *,
    repository: TaskRepository,
    task_input: TaskCreate | dict[str, object],
    idempotency_key: str,
    confirmed: bool,
) -> Task:
    if not confirmed:
        raise PermissionError('create_task requires user confirmation')
    if not idempotency_key:
        raise ValueError('idempotency_key must not be empty')

    task_create = TaskCreate.model_validate(task_input)
    task = Task(
        id=str(uuid4()),
        **task_create.model_dump(),
    )
    return await repository.create(task, idempotency_key=idempotency_key)


async def query_tasks(
    *,
    repository: TaskRepository,
    query: TaskQuery,
) -> TaskListResponse:
    return await repository.list_tasks(query)


async def get_today_tasks(
    *,
    repository: TaskRepository,
    user_id: str,
    timezone_name: str,
    now: datetime | None = None,
) -> TaskListResponse:
    current = now or utc_now()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('now must include timezone information')
    zone = ZoneInfo(timezone_name)
    local_date = current.astimezone(zone).date()
    local_start = datetime.combine(local_date, time.min, tzinfo=zone)
    local_end = datetime.combine(
        local_date + timedelta(days=1), time.min, tzinfo=zone
    )
    return await repository.list_tasks(
        TaskQuery(
            user_id=user_id,
            statuses=_OPEN_STATUSES,
            deadline_from=local_start,
            deadline_to=local_end,
        )
    )


async def get_overdue_tasks(
    *,
    repository: TaskRepository,
    user_id: str,
    now: datetime | None = None,
) -> TaskListResponse:
    current = now or utc_now()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('now must include timezone information')
    result = await repository.list_tasks(
        TaskQuery(
            user_id=user_id,
            statuses=_OPEN_STATUSES,
            overdue_before=current,
            limit=100,
        )
    )
    return result


async def get_task_detail(
    *,
    repository: TaskRepository,
    user_id: str,
    task_id: str,
) -> Task | None:
    return await repository.get(user_id=user_id, task_id=task_id)


async def update_task_status(
    *,
    repository: TaskRepository,
    user_id: str,
    task_id: str,
    target_status: TaskStatus,
    expected_version: int,
    idempotency_key: str,
    confirmed: bool,
    confirmed_reopen: bool = False,
    confirmed_restore: bool = False,
) -> Task:
    if not confirmed:
        raise PermissionError('update_task_status requires user confirmation')
    if not idempotency_key:
        raise ValueError('idempotency_key must not be empty')
    return await repository.update_status(
        user_id=user_id,
        task_id=task_id,
        target_status=target_status,
        expected_version=expected_version,
        confirmed_reopen=confirmed_reopen,
        confirmed_restore=confirmed_restore,
        idempotency_key=idempotency_key,
    )


async def update_task_status_with_rollup(
    *,
    repository: TaskRepository,
    user_id: str,
    task_id: str,
    target_status: TaskStatus,
    expected_version: int,
    idempotency_key: str,
    confirmed: bool,
    confirmed_reopen: bool = False,
    confirmed_restore: bool = False,
) -> TaskStatusUpdateResult:
    if not confirmed:
        raise PermissionError(
            'update_task_status_with_rollup requires user confirmation'
        )
    if not idempotency_key:
        raise ValueError('idempotency_key must not be empty')
    return await repository.update_status_with_rollup(
        user_id=user_id,
        task_id=task_id,
        target_status=target_status,
        expected_version=expected_version,
        confirmed_reopen=confirmed_reopen,
        confirmed_restore=confirmed_restore,
        idempotency_key=idempotency_key,
    )


async def create_subtasks_batch(
    *,
    repository: TaskRepository,
    batch_input: SubtaskBatchCreate | dict[str, object],
    idempotency_key: str,
    confirmed: bool,
) -> SubtaskBatchResult:
    if not confirmed:
        raise PermissionError('create_subtasks_batch requires user confirmation')
    if not idempotency_key:
        raise ValueError('idempotency_key must not be empty')
    batch = SubtaskBatchCreate.model_validate(batch_input)
    return await repository.create_subtasks_batch(
        batch,
        idempotency_key=idempotency_key,
    )


async def update_task(
    *,
    repository: TaskRepository,
    user_id: str,
    task_id: str,
    update: TaskUpdate | dict[str, object],
    idempotency_key: str,
    confirmed: bool,
) -> Task:
    if not confirmed:
        raise PermissionError('update_task requires user confirmation')
    if not idempotency_key:
        raise ValueError('idempotency_key must not be empty')
    task_update = TaskUpdate.model_validate(update)
    if task_update.user_id != user_id:
        raise ValueError('Task update user_id does not match request user_id')
    return await repository.update(
        user_id=user_id,
        task_id=task_id,
        update=task_update,
        idempotency_key=idempotency_key,
    )


async def delete_task(
    *,
    repository: TaskRepository,
    user_id: str,
    task_id: str,
    delete_input: TaskDelete | dict[str, object],
    idempotency_key: str,
    confirmed: bool,
) -> TaskDeleteResult:
    if not confirmed:
        raise PermissionError('delete_task requires user confirmation')
    if not idempotency_key:
        raise ValueError('idempotency_key must not be empty')
    task_delete = TaskDelete.model_validate(delete_input)
    if task_delete.user_id != user_id:
        raise ValueError('Task delete user_id does not match request user_id')
    return await repository.delete(
        user_id=user_id,
        task_id=task_id,
        expected_version=task_delete.expected_version,
        idempotency_key=idempotency_key,
    )


async def delete_tasks_batch(
    *,
    repository: TaskRepository,
    batch_input: TaskDeleteBatch | dict[str, object],
    idempotency_key: str,
    confirmed: bool,
) -> TaskDeleteBatchResult:
    if not confirmed:
        raise PermissionError('delete_tasks_batch requires user confirmation')
    if not idempotency_key:
        raise ValueError('idempotency_key must not be empty')
    batch = TaskDeleteBatch.model_validate(batch_input)
    return await repository.delete_batch(
        batch,
        idempotency_key=idempotency_key,
    )
