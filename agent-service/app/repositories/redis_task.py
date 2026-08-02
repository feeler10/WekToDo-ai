import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

from redis.asyncio import Redis
from redis.exceptions import WatchError

from app.repositories.base import TaskRepository
from app.repositories.exceptions import (
    TaskAlreadyExistsError,
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
    utc_now,
)
from app.services.task_state import validate_status_transition


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

    async def update_status(
        self,
        *,
        user_id: str,
        task_id: str,
        target_status: TaskStatus,
        expected_version: int,
        confirmed_reopen: bool = False,
        idempotency_key: str | None = None,
    ) -> Task:
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
                            ):
                                raise TaskRepositoryConsistencyError(
                                    'Status idempotency key was reused with different input'
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
                    if task.version != expected_version:
                        await pipeline.unwatch()
                        raise TaskVersionConflictError(
                            f'Expected version {expected_version}, got {task.version}'
                        )

                    validate_status_transition(
                        task.status,
                        target_status,
                        confirmed_reopen=confirmed_reopen,
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

                    pipeline.multi()
                    pipeline.set(task_redis_key, updated.model_dump_json())
                    if status_idempotency_key:
                        pipeline.set(
                            status_idempotency_key,
                            json.dumps(
                                {
                                    'task_id': task_id,
                                    'target_status': target_status.value,
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
                task.deadline is None or task.deadline > query.deadline_to
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

    @staticmethod
    def _deserialize(payload: Any) -> Task:
        return Task.model_validate_json(RedisTaskRepository._text(payload))

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode('utf-8')
        return str(value)
