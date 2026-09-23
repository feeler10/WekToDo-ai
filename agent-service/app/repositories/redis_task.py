import json
import hashlib
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from redis.asyncio import Redis
from redis.exceptions import WatchError

from app.repositories.base import TaskRepository
from app.repositories.exceptions import (
    IdempotencyConflictError,
    TaskAlreadyExistsError,
    TaskDeletionBlockedError,
    TaskNotFoundError,
    TaskRepositoryConcurrencyError,
    TaskRepositoryConsistencyError,
    TaskVersionConflictError,
)
from app.schemas.task import (
    Task,
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
    TaskDeleteBatch,
    TaskDeleteBatchResult,
    TaskDeleteResult,
)
from app.services.task_state import (
    TERMINAL_TASK_STATUSES,
    validate_status_transition,
)


class RedisTaskRepository(TaskRepository):
    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = 'wektodo',
        transaction_retries: int = 3,
    ) -> None:
        if transaction_retries < 1:
            raise ValueError('transaction_retries must be at least 1')
        self._redis = redis
        self._key_prefix = key_prefix.strip(':')
        self._transaction_retries = transaction_retries

    async def create(self, task: Task, *, idempotency_key: str) -> Task:
        if not idempotency_key:
            raise ValueError('idempotency_key must not be empty')

        idempotency_redis_key = self._idempotency_key(
            task.user_id,
            idempotency_key,
        )
        task_redis_key = self._task_key(task.user_id, task.id)
        user_index_key = self._user_index_key(task.user_id)

        for _attempt in range(self._transaction_retries):
            try:
                async with self._redis.pipeline(transaction=True) as pipeline:
                    await pipeline.watch(idempotency_redis_key, task_redis_key)
                    existing_task_id = await pipeline.get(idempotency_redis_key)
                    if existing_task_id is not None:
                        existing = await pipeline.get(
                            self._task_key(task.user_id, self._text(existing_task_id))
                        )
                        await pipeline.unwatch()
                        if existing is None:
                            raise TaskRepositoryConsistencyError(
                                'Idempotency key references a missing task'
                            )
                        existing_task = self._deserialize(existing)
                        if existing_task.user_id != task.user_id:
                            raise TaskRepositoryConsistencyError(
                                'Stored task has an invalid user_id'
                            )
                        return existing_task

                    if await pipeline.exists(task_redis_key):
                        await pipeline.unwatch()
                        raise TaskAlreadyExistsError(
                            f'Task already exists for user: {task.id}'
                        )

                    payload = task.model_dump_json()
                    pipeline.multi()
                    pipeline.set(task_redis_key, payload)
                    pipeline.sadd(user_index_key, task.id)
                    pipeline.set(idempotency_redis_key, task.id)
                    await pipeline.execute()
                    return task
            except WatchError:
                continue

        raise TaskRepositoryConcurrencyError(
            'Could not create task after concurrent updates'
        )

    async def get(self, *, user_id: str, task_id: str) -> Task | None:
        payload = await self._redis.get(self._task_key(user_id, task_id))
        if payload is None:
            return None
        task = self._deserialize(payload)
        if task.user_id != user_id:
            raise TaskRepositoryConsistencyError('Stored task has an invalid user_id')
        return task

    async def list_children(
        self,
        *,
        user_id: str,
        parent_id: str,
    ) -> list[Task]:
        child_ids = await self._redis.zrange(
            self._children_index_key(user_id, parent_id),
            0,
            -1,
        )
        if not child_ids:
            return []
        ordered_ids = [self._text(task_id) for task_id in child_ids]
        payloads = await self._redis.mget(
            [self._task_key(user_id, task_id) for task_id in ordered_ids]
        )
        tasks: list[Task] = []
        for payload in payloads:
            if payload is None:
                raise TaskRepositoryConsistencyError(
                    'Child index references a missing task'
                )
            task = self._deserialize(payload)
            if task.user_id != user_id or task.parent_id != parent_id:
                raise TaskRepositoryConsistencyError(
                    'Stored child task has invalid ownership or parent_id'
                )
            tasks.append(task)
        return tasks

    async def create_subtasks_batch(
        self,
        batch: SubtaskBatchCreate,
        *,
        idempotency_key: str,
    ) -> SubtaskBatchResult:
        if not idempotency_key:
            raise ValueError('idempotency_key must not be empty')
        fingerprint = self._batch_fingerprint(batch)
        idempotency_redis_key = self._batch_idempotency_key(
            batch.user_id,
            idempotency_key,
        )
        parent_key = self._task_key(batch.user_id, batch.parent_task_id)
        children_index_key = self._children_index_key(
            batch.user_id,
            batch.parent_task_id,
        )
        child_ids = {
            item.step_key: str(
                uuid5(
                    NAMESPACE_URL,
                    ':'.join(
                        (
                            batch.user_id,
                            batch.parent_task_id,
                            idempotency_key,
                            item.step_key,
                        )
                    ),
                )
            )
            for item in batch.items
        }
        new_task_keys = [
            self._task_key(batch.user_id, task_id)
            for task_id in child_ids.values()
        ]

        for _attempt in range(self._transaction_retries):
            try:
                async with self._redis.pipeline(transaction=True) as pipeline:
                    await pipeline.watch(
                        idempotency_redis_key,
                        parent_key,
                        children_index_key,
                        *new_task_keys,
                    )
                    existing_record = await pipeline.get(idempotency_redis_key)
                    if existing_record is not None:
                        record = json.loads(self._text(existing_record))
                        await pipeline.unwatch()
                        if record.get('fingerprint') != fingerprint:
                            raise IdempotencyConflictError(
                                'Batch idempotency key was reused with different input'
                            )
                        return SubtaskBatchResult(
                            parent_task=record['parent_task'],
                            subtasks=record['subtasks'],
                            replayed=True,
                        )

                    parent_payload = await pipeline.get(parent_key)
                    if parent_payload is None:
                        await pipeline.unwatch()
                        raise TaskNotFoundError(
                            f'Task not found: {batch.parent_task_id}'
                        )
                    parent = self._deserialize(parent_payload)
                    if parent.user_id != batch.user_id:
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Parent task has an invalid user_id'
                        )
                    if parent.parent_id is not None:
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Nested task decomposition is not supported'
                        )
                    if parent.version != batch.expected_parent_version:
                        await pipeline.unwatch()
                        raise TaskVersionConflictError(
                            f'Expected version {batch.expected_parent_version}, '
                            f'got {parent.version}'
                        )
                    if parent.status == TaskStatus.CANCELLED:
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Cancelled parent task cannot receive subtasks'
                        )
                    generated_id_exists = False
                    for key in new_task_keys:
                        if await pipeline.exists(key):
                            generated_id_exists = True
                            break
                    if generated_id_exists:
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Generated child task ID already exists'
                        )

                    existing_ids_raw = await pipeline.zrange(
                        children_index_key,
                        0,
                        -1,
                    )
                    existing_ids = [
                        self._text(task_id) for task_id in existing_ids_raw
                    ]
                    existing_keys = [
                        self._task_key(batch.user_id, task_id)
                        for task_id in existing_ids
                    ]
                    if existing_keys:
                        await pipeline.watch(*existing_keys)
                        existing_payloads = await pipeline.mget(existing_keys)
                    else:
                        existing_payloads = []
                    existing_children = [
                        self._deserialize(payload)
                        for payload in existing_payloads
                        if payload is not None
                    ]
                    if len(existing_children) != len(existing_ids):
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Child index references a missing task'
                        )
                    existing_titles = {
                        self._normalized_title(task.title)
                        for task in existing_children
                        if task.status != TaskStatus.CANCELLED
                    }
                    new_titles = [
                        self._normalized_title(item.title)
                        for item in batch.items
                    ]
                    if len(set(new_titles)) != len(new_titles):
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Batch contains duplicate subtask titles'
                        )
                    if any(
                        title in existing_titles for title in new_titles
                    ):
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Batch contains a duplicate existing subtask'
                        )
                    step_keys = {item.step_key for item in batch.items}
                    if len(step_keys) != len(batch.items):
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Batch step keys must be unique'
                        )
                    orders = {item.order for item in batch.items}
                    if len(orders) != len(batch.items):
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Batch subtask orders must be unique'
                        )
                    order_by_key = {
                        item.step_key: item.order for item in batch.items
                    }
                    for item in batch.items:
                        if (
                            parent.deadline is not None
                            and item.deadline is not None
                            and item.deadline > parent.deadline
                        ):
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Subtask deadline exceeds parent deadline'
                            )
                        if any(
                            dependency not in step_keys
                            or order_by_key[dependency] >= item.order
                            for dependency in item.depends_on
                        ):
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Batch contains an invalid dependency'
                            )

                    now = utc_now()
                    order_offset = max(
                        (
                            task.subtask_order or 0
                            for task in existing_children
                        ),
                        default=0,
                    )
                    subtasks: list[Task] = []
                    for item in sorted(batch.items, key=lambda value: value.order):
                        task_id = child_ids[item.step_key]
                        subtasks.append(
                            Task(
                                id=task_id,
                                user_id=batch.user_id,
                                parent_id=parent.id,
                                title=item.title,
                                description=item.description,
                                deadline=item.deadline,
                                estimated_minutes=item.estimated_minutes,
                                is_ai_generated=True,
                                subtask_order=order_offset + item.order,
                                depends_on_task_ids=[
                                    child_ids[dependency]
                                    for dependency in item.depends_on
                                ],
                                completion_weight=item.completion_weight,
                                creation_source='ai_decomposition',
                                created_at=now,
                                updated_at=now,
                            )
                        )

                    effective_existing = [
                        task
                        for task in existing_children
                        if task.status != TaskStatus.CANCELLED
                    ]
                    effective_count = len(effective_existing) + len(subtasks)
                    done_count = sum(
                        task.status == TaskStatus.DONE
                        for task in effective_existing
                    )
                    progress = (
                        done_count * 100 // effective_count
                        if effective_count
                        else 0
                    )
                    parent_status = (
                        TaskStatus.DOING
                        if parent.status == TaskStatus.DONE
                        else parent.status
                    )
                    updated_parent = Task.model_validate(
                        {
                            **parent.model_dump(),
                            'status': parent_status,
                            'progress': progress,
                            'completed_at': (
                                None
                                if parent_status != TaskStatus.DONE
                                else parent.completed_at
                            ),
                            'updated_at': now,
                            'version': parent.version + 1,
                        }
                    )
                    record = {
                        'fingerprint': fingerprint,
                        'parent_task_id': parent.id,
                        'child_task_ids': [task.id for task in subtasks],
                        'parent_task': updated_parent.model_dump(mode='json'),
                        'subtasks': [
                            task.model_dump(mode='json') for task in subtasks
                        ],
                    }

                    pipeline.multi()
                    for task in subtasks:
                        pipeline.set(
                            self._task_key(batch.user_id, task.id),
                            task.model_dump_json(),
                        )
                    pipeline.sadd(
                        self._user_index_key(batch.user_id),
                        *(task.id for task in subtasks),
                    )
                    pipeline.zadd(
                        children_index_key,
                        {
                            task.id: task.subtask_order or 0
                            for task in subtasks
                        },
                    )
                    pipeline.set(parent_key, updated_parent.model_dump_json())
                    pipeline.set(idempotency_redis_key, json.dumps(record))
                    await pipeline.execute()
                    return SubtaskBatchResult(
                        parent_task=updated_parent,
                        subtasks=subtasks,
                    )
            except WatchError:
                continue

        raise TaskRepositoryConcurrencyError(
            'Could not create subtask batch after concurrent updates'
        )

    async def update(
        self,
        *,
        user_id: str,
        task_id: str,
        update: TaskUpdate,
        idempotency_key: str | None = None,
    ) -> Task:
        if update.user_id != user_id:
            raise TaskRepositoryConsistencyError(
                'Task update user_id does not match request user_id'
            )
        task_redis_key = self._task_key(user_id, task_id)
        redis_idempotency_key = (
            self._update_idempotency_key(user_id, idempotency_key)
            if idempotency_key
            else None
        )
        change_payload = update.model_dump(
            mode='json',
            exclude_unset=True,
            exclude={'user_id', 'expected_version'},
        )

        for _attempt in range(self._transaction_retries):
            try:
                async with self._redis.pipeline(transaction=True) as pipeline:
                    watch_keys = [task_redis_key]
                    if redis_idempotency_key:
                        watch_keys.append(redis_idempotency_key)
                    await pipeline.watch(*watch_keys)
                    if redis_idempotency_key:
                        existing_update = await pipeline.get(
                            redis_idempotency_key
                        )
                        if existing_update is not None:
                            record = json.loads(self._text(existing_update))
                            await pipeline.unwatch()
                            if (
                                record.get('task_id') != task_id
                                or record.get('changes') != change_payload
                            ):
                                raise IdempotencyConflictError(
                                    'Task update idempotency key was reused '
                                    'with different input'
                                )
                            replayed = Task.model_validate(record.get('task'))
                            if replayed.user_id != user_id:
                                raise TaskRepositoryConsistencyError(
                                    'Stored task has an invalid user_id'
                                )
                            return replayed

                    payload = await pipeline.get(task_redis_key)
                    if payload is None:
                        await pipeline.unwatch()
                        raise TaskNotFoundError(f'Task not found: {task_id}')
                    task = self._deserialize(payload)
                    if task.user_id != user_id:
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Stored task has an invalid user_id'
                        )
                    if task.version != update.expected_version:
                        await pipeline.unwatch()
                        raise TaskVersionConflictError(
                            f'Expected version {update.expected_version}, '
                            f'got {task.version}'
                        )

                    merged = {**task.model_dump(), **change_payload}
                    user_priority = merged.get('user_priority')
                    ai_priority = merged.get('ai_priority')
                    merged['effective_priority'] = user_priority or ai_priority
                    merged['priority_source'] = (
                        'user' if user_priority else ('ai' if ai_priority else None)
                    )
                    merged['updated_at'] = utc_now()
                    merged['version'] = task.version + 1
                    updated = Task.model_validate(merged)

                    pipeline.multi()
                    pipeline.set(task_redis_key, updated.model_dump_json())
                    if redis_idempotency_key:
                        pipeline.set(
                            redis_idempotency_key,
                            json.dumps(
                                {
                                    'task_id': task_id,
                                    'changes': change_payload,
                                    'task': updated.model_dump(mode='json'),
                                }
                            ),
                        )
                    await pipeline.execute()
                    return updated
            except WatchError:
                continue

        raise TaskRepositoryConcurrencyError(
            'Could not update task after concurrent updates'
        )

    async def list_tasks(self, query: TaskQuery) -> TaskListResponse:
        task_ids = await self._redis.smembers(self._user_index_key(query.user_id))
        if not task_ids:
            return TaskListResponse(items=[], total=0)

        ordered_ids = sorted(self._text(task_id) for task_id in task_ids)
        keys = [self._task_key(query.user_id, task_id) for task_id in ordered_ids]
        payloads = await self._redis.mget(keys)
        tasks = [
            self._deserialize(payload)
            for payload in payloads
            if payload is not None
        ]
        for task in tasks:
            if task.user_id != query.user_id:
                raise TaskRepositoryConsistencyError(
                    'Stored task has an invalid user_id'
                )

        filtered = list(self._filter_tasks(tasks, query))
        filtered.sort(key=lambda task: (task.created_at, task.id), reverse=True)
        total = len(filtered)
        items = filtered[query.offset : query.offset + query.limit]
        return TaskListResponse(items=items, total=total)

    async def delete(
        self,
        *,
        user_id: str,
        task_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> TaskDeleteResult:
        if not idempotency_key:
            raise ValueError('idempotency_key must not be empty')
        task_key = self._task_key(user_id, task_id)
        user_index_key = self._user_index_key(user_id)
        own_children_index_key = self._children_index_key(user_id, task_id)
        deletion_idempotency_key = self._delete_idempotency_key(
            user_id,
            idempotency_key,
        )

        for _attempt in range(self._transaction_retries):
            try:
                async with self._redis.pipeline(transaction=True) as pipeline:
                    await pipeline.watch(
                        deletion_idempotency_key,
                        task_key,
                        user_index_key,
                        own_children_index_key,
                    )
                    existing_record = await pipeline.get(
                        deletion_idempotency_key
                    )
                    if existing_record is not None:
                        record = json.loads(self._text(existing_record))
                        await pipeline.unwatch()
                        if (
                            record.get('task_id') != task_id
                            or record.get('expected_version') != expected_version
                        ):
                            raise IdempotencyConflictError(
                                'Task delete idempotency key was reused '
                                'with different input'
                            )
                        parent_data = record.get('parent_task')
                        parent_task = (
                            Task.model_validate(parent_data)
                            if parent_data is not None
                            else None
                        )
                        if (
                            parent_task is not None
                            and parent_task.user_id != user_id
                        ):
                            raise TaskRepositoryConsistencyError(
                                'Stored parent task has an invalid user_id'
                            )
                        return TaskDeleteResult(
                            deleted_task_id=task_id,
                            parent_task=parent_task,
                            replayed=True,
                        )

                    payload = await pipeline.get(task_key)
                    if payload is None:
                        await pipeline.unwatch()
                        raise TaskNotFoundError(f'Task not found: {task_id}')
                    task = self._deserialize(payload)
                    if task.user_id != user_id:
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Stored task has an invalid user_id'
                        )
                    if task.version != expected_version:
                        await pipeline.unwatch()
                        raise TaskVersionConflictError(
                            f'Expected version {expected_version}, '
                            f'got {task.version}'
                        )
                    if not await pipeline.sismember(user_index_key, task_id):
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Task is missing from the user index'
                        )

                    direct_child_ids = await pipeline.zrange(
                        own_children_index_key,
                        0,
                        -1,
                    )
                    if direct_child_ids:
                        await pipeline.unwatch()
                        raise TaskDeletionBlockedError(
                            'Task has direct subtasks and cannot be deleted'
                        )

                    parent_task: Task | None = None
                    parent_key: str | None = None
                    parent_children_index_key: str | None = None
                    if task.parent_id is not None:
                        parent_key = self._task_key(user_id, task.parent_id)
                        parent_children_index_key = self._children_index_key(
                            user_id,
                            task.parent_id,
                        )
                        await pipeline.watch(
                            parent_key,
                            parent_children_index_key,
                        )
                        parent_payload = await pipeline.get(parent_key)
                        if parent_payload is None:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Child task references a missing parent'
                            )
                        current_parent = self._deserialize(parent_payload)
                        if current_parent.user_id != user_id:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Parent task has an invalid user_id'
                            )

                        sibling_ids_raw = await pipeline.zrange(
                            parent_children_index_key,
                            0,
                            -1,
                        )
                        sibling_ids = [
                            self._text(sibling_id)
                            for sibling_id in sibling_ids_raw
                        ]
                        if task_id not in sibling_ids:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Child task is missing from the parent index'
                            )
                        sibling_keys = [
                            self._task_key(user_id, sibling_id)
                            for sibling_id in sibling_ids
                        ]
                        if sibling_keys:
                            await pipeline.watch(*sibling_keys)
                            sibling_payloads = await pipeline.mget(sibling_keys)
                        else:
                            sibling_payloads = []
                        siblings = [
                            self._deserialize(sibling_payload)
                            for sibling_payload in sibling_payloads
                            if sibling_payload is not None
                        ]
                        if len(siblings) != len(sibling_ids):
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Child index references a missing task'
                            )
                        if any(
                            sibling.user_id != user_id
                            or sibling.parent_id != task.parent_id
                            for sibling in siblings
                        ):
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Stored child task has invalid ownership or parent_id'
                            )
                        blockers = [
                            sibling.title
                            for sibling in siblings
                            if sibling.id != task_id
                            and task_id in sibling.depends_on_task_ids
                        ]
                        if blockers:
                            await pipeline.unwatch()
                            raise TaskDeletionBlockedError(
                                'Task is required by: ' + '、'.join(blockers)
                            )

                        remaining = [
                            sibling
                            for sibling in siblings
                            if sibling.id != task_id
                        ]
                        effective = [
                            sibling
                            for sibling in remaining
                            if sibling.status != TaskStatus.CANCELLED
                        ]
                        done_count = sum(
                            sibling.status == TaskStatus.DONE
                            for sibling in effective
                        )
                        progress = (
                            done_count * 100 // len(effective)
                            if effective
                            else 0
                        )
                        all_done = bool(effective) and done_count == len(effective)
                        now = utc_now()
                        parent_status = current_parent.status
                        completed_at = current_parent.completed_at
                        if current_parent.status == TaskStatus.CANCELLED:
                            completed_at = None
                        elif all_done:
                            parent_status = TaskStatus.DONE
                            completed_at = current_parent.completed_at or now
                            progress = 100
                        elif current_parent.status == TaskStatus.DONE:
                            parent_status = TaskStatus.DOING
                            completed_at = None
                        parent_task = Task.model_validate(
                            {
                                **current_parent.model_dump(),
                                'status': parent_status,
                                'progress': progress,
                                'completed_at': completed_at,
                                'updated_at': now,
                                'version': current_parent.version + 1,
                            }
                        )

                    record = {
                        'task_id': task_id,
                        'expected_version': expected_version,
                        'parent_task': (
                            parent_task.model_dump(mode='json')
                            if parent_task is not None
                            else None
                        ),
                    }
                    pipeline.multi()
                    pipeline.delete(task_key)
                    pipeline.srem(user_index_key, task_id)
                    pipeline.delete(own_children_index_key)
                    if (
                        parent_task is not None
                        and parent_key is not None
                        and parent_children_index_key is not None
                    ):
                        pipeline.zrem(parent_children_index_key, task_id)
                        pipeline.set(parent_key, parent_task.model_dump_json())
                    pipeline.set(
                        deletion_idempotency_key,
                        json.dumps(record),
                    )
                    await pipeline.execute()
                    return TaskDeleteResult(
                        deleted_task_id=task_id,
                        parent_task=parent_task,
                    )
            except WatchError:
                continue

        raise TaskRepositoryConcurrencyError(
            'Could not delete task after concurrent updates'
        )

    async def delete_batch(
        self,
        batch: TaskDeleteBatch,
        *,
        idempotency_key: str,
    ) -> TaskDeleteBatchResult:
        if not idempotency_key:
            raise ValueError('idempotency_key must not be empty')
        fingerprint = hashlib.sha256(
            json.dumps(
                batch.model_dump(mode='json'),
                ensure_ascii=False,
                sort_keys=True,
                separators=(',', ':'),
            ).encode('utf-8')
        ).hexdigest()
        target_ids = [item.task_id for item in batch.items]
        expected_versions = {
            item.task_id: item.expected_version for item in batch.items
        }
        target_set = set(target_ids)
        target_keys = [
            self._task_key(batch.user_id, task_id) for task_id in target_ids
        ]
        own_children_keys = [
            self._children_index_key(batch.user_id, task_id)
            for task_id in target_ids
        ]
        user_index_key = self._user_index_key(batch.user_id)
        idempotency_redis_key = self._delete_batch_idempotency_key(
            batch.user_id,
            idempotency_key,
        )

        for _attempt in range(self._transaction_retries):
            try:
                async with self._redis.pipeline(transaction=True) as pipeline:
                    await pipeline.watch(
                        idempotency_redis_key,
                        user_index_key,
                        *target_keys,
                        *own_children_keys,
                    )
                    existing_record = await pipeline.get(idempotency_redis_key)
                    if existing_record is not None:
                        record = json.loads(self._text(existing_record))
                        await pipeline.unwatch()
                        if record.get('fingerprint') != fingerprint:
                            raise IdempotencyConflictError(
                                'Task delete batch idempotency key was reused '
                                'with different input'
                            )
                        parent_tasks = [
                            Task.model_validate(item)
                            for item in record.get('parent_tasks', [])
                        ]
                        if any(
                            parent.user_id != batch.user_id
                            for parent in parent_tasks
                        ):
                            raise TaskRepositoryConsistencyError(
                                'Stored parent task has an invalid user_id'
                            )
                        return TaskDeleteBatchResult(
                            deleted_task_ids=list(record['deleted_task_ids']),
                            parent_tasks=parent_tasks,
                            replayed=True,
                        )

                    payloads = await pipeline.mget(target_keys)
                    if any(payload is None for payload in payloads):
                        await pipeline.unwatch()
                        raise TaskNotFoundError(
                            'One or more tasks were not found'
                        )
                    tasks = [self._deserialize(payload) for payload in payloads]
                    for task in tasks:
                        if task.user_id != batch.user_id:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Stored task has an invalid user_id'
                            )
                        if task.version != expected_versions[task.id]:
                            await pipeline.unwatch()
                            raise TaskVersionConflictError(
                                f'Expected version {expected_versions[task.id]}, '
                                f'got {task.version}'
                            )
                        if not await pipeline.sismember(user_index_key, task.id):
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Task is missing from the user index'
                            )

                    for task, children_key in zip(
                        tasks,
                        own_children_keys,
                        strict=True,
                    ):
                        direct_children = [
                            self._text(value)
                            for value in await pipeline.zrange(
                                children_key,
                                0,
                                -1,
                            )
                        ]
                        outside_batch = [
                            child_id
                            for child_id in direct_children
                            if child_id not in target_set
                        ]
                        if direct_children:
                            await pipeline.unwatch()
                            detail = (
                                'outside batch'
                                if outside_batch
                                else 'inside batch'
                            )
                            raise TaskDeletionBlockedError(
                                f'Task has direct subtasks {detail}: {task.title}'
                            )

                    parent_ids = sorted(
                        {
                            task.parent_id
                            for task in tasks
                            if task.parent_id is not None
                        }
                    )
                    parent_keys = {
                        parent_id: self._task_key(batch.user_id, parent_id)
                        for parent_id in parent_ids
                    }
                    parent_index_keys = {
                        parent_id: self._children_index_key(
                            batch.user_id,
                            parent_id,
                        )
                        for parent_id in parent_ids
                    }
                    if parent_ids:
                        await pipeline.watch(
                            *(parent_keys[parent_id] for parent_id in parent_ids),
                            *(
                                parent_index_keys[parent_id]
                                for parent_id in parent_ids
                            ),
                        )

                    current_parents: dict[str, Task] = {}
                    sibling_ids_by_parent: dict[str, list[str]] = {}
                    sibling_keys: set[str] = set()
                    for parent_id in parent_ids:
                        parent_payload = await pipeline.get(parent_keys[parent_id])
                        if parent_payload is None:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Child task references a missing parent'
                            )
                        parent = self._deserialize(parent_payload)
                        if parent.user_id != batch.user_id:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Parent task has an invalid user_id'
                            )
                        current_parents[parent_id] = parent
                        sibling_ids = [
                            self._text(value)
                            for value in await pipeline.zrange(
                                parent_index_keys[parent_id],
                                0,
                                -1,
                            )
                        ]
                        sibling_ids_by_parent[parent_id] = sibling_ids
                        sibling_keys.update(
                            self._task_key(batch.user_id, sibling_id)
                            for sibling_id in sibling_ids
                        )
                    if sibling_keys:
                        await pipeline.watch(*sorted(sibling_keys))

                    updated_parents: list[Task] = []
                    now = utc_now()
                    for parent_id in parent_ids:
                        sibling_ids = sibling_ids_by_parent[parent_id]
                        deleting_from_parent = {
                            task.id
                            for task in tasks
                            if task.parent_id == parent_id
                        }
                        if not deleting_from_parent.issubset(set(sibling_ids)):
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Child task is missing from the parent index'
                            )
                        sibling_payloads = await pipeline.mget(
                            [
                                self._task_key(batch.user_id, sibling_id)
                                for sibling_id in sibling_ids
                            ]
                        )
                        if any(value is None for value in sibling_payloads):
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Child index references a missing task'
                            )
                        siblings = [
                            self._deserialize(value) for value in sibling_payloads
                        ]
                        if any(
                            sibling.user_id != batch.user_id
                            or sibling.parent_id != parent_id
                            for sibling in siblings
                        ):
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Stored child task has invalid ownership or parent_id'
                            )
                        blockers = [
                            sibling.title
                            for sibling in siblings
                            if sibling.id not in target_set
                            and target_set.intersection(
                                sibling.depends_on_task_ids
                            )
                        ]
                        if blockers:
                            await pipeline.unwatch()
                            raise TaskDeletionBlockedError(
                                'Tasks are required by: ' + '、'.join(blockers)
                            )
                        remaining = [
                            sibling
                            for sibling in siblings
                            if sibling.id not in target_set
                        ]
                        effective = [
                            sibling
                            for sibling in remaining
                            if sibling.status != TaskStatus.CANCELLED
                        ]
                        done_count = sum(
                            sibling.status == TaskStatus.DONE
                            for sibling in effective
                        )
                        progress = (
                            done_count * 100 // len(effective)
                            if effective
                            else 0
                        )
                        all_done = bool(effective) and done_count == len(effective)
                        current_parent = current_parents[parent_id]
                        parent_status = current_parent.status
                        completed_at = current_parent.completed_at
                        if current_parent.status == TaskStatus.CANCELLED:
                            completed_at = None
                        elif all_done:
                            parent_status = TaskStatus.DONE
                            completed_at = current_parent.completed_at or now
                            progress = 100
                        elif current_parent.status == TaskStatus.DONE:
                            parent_status = TaskStatus.DOING
                            completed_at = None
                        updated_parents.append(
                            Task.model_validate(
                                {
                                    **current_parent.model_dump(),
                                    'status': parent_status,
                                    'progress': progress,
                                    'completed_at': completed_at,
                                    'updated_at': now,
                                    'version': current_parent.version + 1,
                                }
                            )
                        )

                    record = {
                        'fingerprint': fingerprint,
                        'deleted_task_ids': target_ids,
                        'parent_tasks': [
                            parent.model_dump(mode='json')
                            for parent in updated_parents
                        ],
                    }
                    pipeline.multi()
                    pipeline.delete(*target_keys)
                    pipeline.srem(user_index_key, *target_ids)
                    pipeline.delete(*own_children_keys)
                    for parent_id in parent_ids:
                        deleting_from_parent = [
                            task.id
                            for task in tasks
                            if task.parent_id == parent_id
                        ]
                        pipeline.zrem(
                            parent_index_keys[parent_id],
                            *deleting_from_parent,
                        )
                    for parent in updated_parents:
                        pipeline.set(
                            parent_keys[parent.id],
                            parent.model_dump_json(),
                        )
                    pipeline.set(idempotency_redis_key, json.dumps(record))
                    await pipeline.execute()
                    return TaskDeleteBatchResult(
                        deleted_task_ids=target_ids,
                        parent_tasks=updated_parents,
                    )
            except WatchError:
                continue

        raise TaskRepositoryConcurrencyError(
            'Could not delete task batch after concurrent updates'
        )

    async def update_status(
        self,
        *,
        user_id: str,
        task_id: str,
        target_status: TaskStatus,
        expected_version: int,
        confirmed_reopen: bool = False,
        confirmed_restore: bool = False,
        idempotency_key: str | None = None,
    ) -> Task:
        result = await self.update_status_with_rollup(
            user_id=user_id,
            task_id=task_id,
            target_status=target_status,
            expected_version=expected_version,
            confirmed_reopen=confirmed_reopen,
            confirmed_restore=confirmed_restore,
            idempotency_key=idempotency_key,
        )
        return result.task

    async def update_status_with_rollup(
        self,
        *,
        user_id: str,
        task_id: str,
        target_status: TaskStatus,
        expected_version: int,
        confirmed_reopen: bool = False,
        confirmed_restore: bool = False,
        idempotency_key: str | None = None,
    ) -> TaskStatusUpdateResult:
        task_redis_key = self._task_key(user_id, task_id)
        status_idempotency_key = (
            self._status_idempotency_key(user_id, idempotency_key)
            if idempotency_key
            else None
        )

        for _attempt in range(self._transaction_retries):
            try:
                async with self._redis.pipeline(transaction=True) as pipeline:
                    watch_keys = [task_redis_key]
                    if status_idempotency_key:
                        watch_keys.append(status_idempotency_key)
                    await pipeline.watch(*watch_keys)
                    if status_idempotency_key:
                        existing_update = await pipeline.get(status_idempotency_key)
                        if existing_update is not None:
                            record = json.loads(self._text(existing_update))
                            await pipeline.unwatch()
                            if (
                                record.get('task_id') != task_id
                                or record.get('target_status') != target_status.value
                                or record.get('expected_version') != expected_version
                                or record.get('confirmed_reopen') != confirmed_reopen
                                or record.get('confirmed_restore') != confirmed_restore
                            ):
                                raise IdempotencyConflictError(
                                    'Status idempotency key was reused with different input'
                                )
                            replayed = Task.model_validate(record.get('task'))
                            if replayed.user_id != user_id:
                                raise TaskRepositoryConsistencyError(
                                    'Stored task has an invalid user_id'
                                )
                            parent_data = record.get('parent_task')
                            return TaskStatusUpdateResult(
                                task=replayed,
                                parent_task=(
                                    Task.model_validate(parent_data)
                                    if parent_data is not None
                                    else None
                                ),
                            )
                    payload = await pipeline.get(task_redis_key)
                    if payload is None:
                        await pipeline.unwatch()
                        raise TaskNotFoundError(f'Task not found: {task_id}')

                    task = self._deserialize(payload)
                    if task.user_id != user_id:
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Stored task has an invalid user_id'
                        )
                    if task.version != expected_version:
                        await pipeline.unwatch()
                        raise TaskVersionConflictError(
                            f'Expected version {expected_version}, got {task.version}'
                        )

                    relation_parent: Task | None = None
                    relation_parent_key: str | None = None
                    children_index_key = self._children_index_key(
                        user_id,
                        task.parent_id or task.id,
                    )
                    additional_watch_keys = [children_index_key]
                    if task.parent_id is not None:
                        relation_parent_key = self._task_key(
                            user_id,
                            task.parent_id,
                        )
                        additional_watch_keys.append(relation_parent_key)
                    await pipeline.watch(*additional_watch_keys)

                    if relation_parent_key is not None:
                        relation_parent_payload = await pipeline.get(
                            relation_parent_key
                        )
                        if relation_parent_payload is None:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Child task references a missing parent'
                            )
                        relation_parent = self._deserialize(
                            relation_parent_payload
                        )
                        if relation_parent.user_id != user_id:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Parent task has an invalid user_id'
                            )
                        if relation_parent.status == TaskStatus.CANCELLED:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Cannot update a child of a cancelled parent'
                            )

                    child_ids_raw = await pipeline.zrange(
                        children_index_key,
                        0,
                        -1,
                    )
                    child_ids = [
                        self._text(child_id) for child_id in child_ids_raw
                    ]
                    child_keys = [
                        self._task_key(user_id, child_id)
                        for child_id in child_ids
                    ]
                    if child_keys:
                        await pipeline.watch(*child_keys)
                        child_payloads = await pipeline.mget(child_keys)
                    else:
                        child_payloads = []
                    children = [
                        self._deserialize(child_payload)
                        for child_payload in child_payloads
                        if child_payload is not None
                    ]
                    if len(children) != len(child_ids):
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Child index references a missing task'
                        )
                    if task.parent_id is not None and task.id not in child_ids:
                        await pipeline.unwatch()
                        raise TaskRepositoryConsistencyError(
                            'Child task is missing from the parent index'
                        )

                    validate_status_transition(
                        task.status,
                        target_status,
                        confirmed_reopen=confirmed_reopen,
                        confirmed_restore=confirmed_restore,
                    )
                    now = utc_now()
                    completed_at = now if target_status == TaskStatus.DONE else None
                    updated = Task.model_validate(
                        {
                            **task.model_dump(),
                            'status': target_status,
                            'completed_at': completed_at,
                            'updated_at': now,
                            'version': task.version + 1,
                        }
                    )

                    updated_parent: Task | None = None
                    if relation_parent is not None:
                        rolled_children = [
                            updated if child.id == updated.id else child
                            for child in children
                        ]
                        effective = [
                            child
                            for child in rolled_children
                            if child.status != TaskStatus.CANCELLED
                        ]
                        done_count = sum(
                            child.status == TaskStatus.DONE
                            for child in effective
                        )
                        progress = (
                            done_count * 100 // len(effective)
                            if effective
                            else 0
                        )
                        all_done = bool(effective) and done_count == len(effective)
                        parent_status = relation_parent.status
                        parent_completed_at = relation_parent.completed_at
                        if all_done:
                            parent_status = TaskStatus.DONE
                            parent_completed_at = now
                            progress = 100
                        elif parent_status == TaskStatus.DONE:
                            parent_status = TaskStatus.DOING
                            parent_completed_at = None
                        updated_parent = Task.model_validate(
                            {
                                **relation_parent.model_dump(),
                                'status': parent_status,
                                'progress': progress,
                                'completed_at': parent_completed_at,
                                'updated_at': now,
                                'version': relation_parent.version + 1,
                            }
                        )
                    elif children:
                        effective = [
                            child
                            for child in children
                            if child.status != TaskStatus.CANCELLED
                        ]
                        all_done = bool(effective) and all(
                            child.status == TaskStatus.DONE
                            for child in effective
                        )
                        if target_status == TaskStatus.DONE and not all_done:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Parent task cannot complete before its subtasks'
                            )
                        if all_done and target_status != TaskStatus.DONE:
                            await pipeline.unwatch()
                            raise TaskRepositoryConsistencyError(
                                'Parent task must remain DONE while all subtasks are done'
                            )

                    pipeline.multi()
                    pipeline.set(task_redis_key, updated.model_dump_json())
                    if updated_parent is not None and relation_parent_key is not None:
                        pipeline.set(
                            relation_parent_key,
                            updated_parent.model_dump_json(),
                        )
                    if status_idempotency_key:
                        pipeline.set(
                            status_idempotency_key,
                            json.dumps(
                                {
                                    'task_id': task_id,
                                    'target_status': target_status.value,
                                    'expected_version': expected_version,
                                    'confirmed_reopen': confirmed_reopen,
                                    'confirmed_restore': confirmed_restore,
                                    'task': updated.model_dump(mode='json'),
                                    'parent_task': (
                                        updated_parent.model_dump(mode='json')
                                        if updated_parent is not None
                                        else None
                                    ),
                                }
                            ),
                        )
                    await pipeline.execute()
                    return TaskStatusUpdateResult(
                        task=updated,
                        parent_task=updated_parent,
                    )
            except WatchError:
                continue

        raise TaskRepositoryConcurrencyError(
            'Could not update task after concurrent updates'
        )

    def _filter_tasks(
        self,
        tasks: Iterable[Task],
        query: TaskQuery,
    ) -> Iterable[Task]:
        for task in tasks:
            if query.statuses is not None and task.status not in query.statuses:
                continue
            if (
                query.priorities is not None
                and task.effective_priority not in query.priorities
            ):
                continue
            if query.category is not None and task.category != query.category:
                continue
            if query.deadline_from is not None and (
                task.deadline is None or task.deadline < query.deadline_from
            ):
                continue
            if query.deadline_to is not None and (
                task.deadline is None or task.deadline >= query.deadline_to
            ):
                continue
            if query.overdue_before is not None and (
                task.deadline is None
                or task.deadline >= query.overdue_before
                or task.status in TERMINAL_TASK_STATUSES
            ):
                continue

            yield task

    def _key(self, *parts: str) -> str:
        encoded_parts = (quote(part, safe='') for part in parts)
        return ':'.join((self._key_prefix, *encoded_parts))

    def _task_key(self, user_id: str, task_id: str) -> str:
        return self._key('task', user_id, task_id)

    def _user_index_key(self, user_id: str) -> str:
        return self._key('tasks', user_id)

    def _children_index_key(self, user_id: str, parent_id: str) -> str:
        return self._key('task_children', user_id, parent_id)

    def _idempotency_key(self, user_id: str, idempotency_key: str) -> str:
        return self._key('idempotency', 'create_task', user_id, idempotency_key)

    def _status_idempotency_key(
        self,
        user_id: str,
        idempotency_key: str,
    ) -> str:
        return self._key(
            'idempotency',
            'update_task_status',
            user_id,
            idempotency_key,
        )

    def _update_idempotency_key(
        self,
        user_id: str,
        idempotency_key: str,
    ) -> str:
        return self._key(
            'idempotency',
            'update_task',
            user_id,
            idempotency_key,
        )

    def _batch_idempotency_key(
        self,
        user_id: str,
        idempotency_key: str,
    ) -> str:
        return self._key(
            'idempotency',
            'create_subtasks_batch',
            user_id,
            idempotency_key,
        )

    def _delete_idempotency_key(
        self,
        user_id: str,
        idempotency_key: str,
    ) -> str:
        return self._key(
            'idempotency',
            'delete_task',
            user_id,
            idempotency_key,
        )

    def _delete_batch_idempotency_key(
        self,
        user_id: str,
        idempotency_key: str,
    ) -> str:
        return self._key(
            'idempotency',
            'delete_tasks_batch',
            user_id,
            idempotency_key,
        )

    @staticmethod
    def _batch_fingerprint(batch: SubtaskBatchCreate) -> str:
        payload = json.dumps(
            batch.model_dump(mode='json'),
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
        )
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    @staticmethod
    def _normalized_title(value: str) -> str:
        return re.sub(r'[\W_]+', '', value, flags=re.UNICODE).casefold()

    @staticmethod
    def _deserialize(payload: Any) -> Task:
        return Task.model_validate_json(RedisTaskRepository._text(payload))

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode('utf-8')
        return str(value)
