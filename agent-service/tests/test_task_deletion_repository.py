from datetime import datetime, timezone

import pytest
from fakeredis.aioredis import FakeRedis

from app.repositories.exceptions import (
    TaskDeletionBlockedError,
    TaskNotFoundError,
    TaskRepositoryConsistencyError,
    TaskVersionConflictError,
)
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.subtask import SubtaskBatchCreate
from app.schemas.task import Task, TaskQuery, TaskStatus
from app.schemas.task_deletion import (
    TaskDelete,
    TaskDeleteBatch,
    TaskDeleteBatchItem,
)
from app.tools.task_tools import delete_task, delete_tasks_batch


def _task(task_id: str = 'task-1', *, user_id: str = 'user-1') -> Task:
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    return Task(
        id=task_id,
        user_id=user_id,
        title='待删除任务',
        created_at=now,
        updated_at=now,
    )


def _batch() -> SubtaskBatchCreate:
    return SubtaskBatchCreate.model_validate(
        {
            'user_id': 'user-1',
            'parent_task_id': 'parent-1',
            'expected_parent_version': 1,
            'items': [
                {'step_key': 'one', 'title': '步骤一', 'order': 1},
                {
                    'step_key': 'two',
                    'title': '步骤二',
                    'order': 2,
                    'depends_on': ['one'],
                },
                {
                    'step_key': 'three',
                    'title': '步骤三',
                    'order': 3,
                    'depends_on': ['two'],
                },
            ],
        }
    )


async def _repository_with_subtasks(
    redis: FakeRedis,
    *,
    key_prefix: str,
) -> tuple[RedisTaskRepository, list[Task]]:
    repository = RedisTaskRepository(redis, key_prefix=key_prefix)
    parent = _task('parent-1').model_copy(
        update={'title': '父任务', 'status': TaskStatus.DOING}
    )
    await repository.create(parent, idempotency_key='parent')
    created = await repository.create_subtasks_batch(
        _batch(),
        idempotency_key='batch',
    )
    return repository, created.subtasks


@pytest.mark.anyio
async def test_delete_leaf_removes_task_and_replays_idempotently() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='delete:leaf')
    try:
        await repository.create(_task(), idempotency_key='create')
        result = await repository.delete(
            user_id='user-1',
            task_id='task-1',
            expected_version=1,
            idempotency_key='delete-1',
        )
        replay = await repository.delete(
            user_id='user-1',
            task_id='task-1',
            expected_version=1,
            idempotency_key='delete-1',
        )

        assert result.deleted_task_id == 'task-1'
        assert replay.replayed is True
        assert await repository.get(user_id='user-1', task_id='task-1') is None
        listed = await repository.list_tasks(TaskQuery(user_id='user-1'))
        assert listed.items == []
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_tool_requires_confirmation() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='delete:confirmation')
    try:
        await repository.create(_task(), idempotency_key='create')
        with pytest.raises(PermissionError):
            await delete_task(
                repository=repository,
                user_id='user-1',
                task_id='task-1',
                delete_input=TaskDelete(
                    user_id='user-1',
                    expected_version=1,
                ),
                idempotency_key='delete-1',
                confirmed=False,
            )
        assert await repository.get(user_id='user-1', task_id='task-1')
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_batch_is_atomic_and_idempotent() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='delete:batch')
    batch = TaskDeleteBatch(
        user_id='user-1',
        items=[
            TaskDeleteBatchItem(task_id='task-1', expected_version=1),
            TaskDeleteBatchItem(task_id='task-2', expected_version=1),
        ],
    )
    try:
        await repository.create(_task('task-1'), idempotency_key='create-1')
        await repository.create(_task('task-2'), idempotency_key='create-2')

        result = await delete_tasks_batch(
            repository=repository,
            batch_input=batch,
            idempotency_key='delete-batch',
            confirmed=True,
        )
        replay = await repository.delete_batch(
            batch,
            idempotency_key='delete-batch',
        )

        assert result.deleted_task_ids == ['task-1', 'task-2']
        assert replay.replayed is True
        assert await repository.get(user_id='user-1', task_id='task-1') is None
        assert await repository.get(user_id='user-1', task_id='task-2') is None
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_batch_stale_item_prevents_every_delete() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='delete:batch-stale')
    try:
        await repository.create(_task('task-1'), idempotency_key='create-1')
        await repository.create(_task('task-2'), idempotency_key='create-2')
        await repository.update_status(
            user_id='user-1',
            task_id='task-2',
            target_status=TaskStatus.DOING,
            expected_version=1,
            idempotency_key='update-2',
        )
        batch = TaskDeleteBatch(
            user_id='user-1',
            items=[
                TaskDeleteBatchItem(task_id='task-1', expected_version=1),
                TaskDeleteBatchItem(task_id='task-2', expected_version=1),
            ],
        )

        with pytest.raises(TaskVersionConflictError):
            await repository.delete_batch(batch, idempotency_key='stale')

        assert await repository.get(user_id='user-1', task_id='task-1')
        assert await repository.get(user_id='user-1', task_id='task-2')
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_rejects_parent_with_direct_children() -> None:
    redis = FakeRedis(decode_responses=True)
    try:
        repository, _children = await _repository_with_subtasks(
            redis,
            key_prefix='delete:parent',
        )
        with pytest.raises(TaskDeletionBlockedError, match='direct subtasks'):
            await repository.delete(
                user_id='user-1',
                task_id='parent-1',
                expected_version=2,
                idempotency_key='delete-parent',
            )
        assert await repository.get(user_id='user-1', task_id='parent-1')
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_rejects_child_required_by_sibling() -> None:
    redis = FakeRedis(decode_responses=True)
    try:
        repository, children = await _repository_with_subtasks(
            redis,
            key_prefix='delete:dependency',
        )
        with pytest.raises(TaskDeletionBlockedError, match='步骤二'):
            await repository.delete(
                user_id='user-1',
                task_id=children[0].id,
                expected_version=1,
                idempotency_key='delete-child',
            )
        assert await repository.get(
            user_id='user-1', task_id=children[0].id
        )
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_child_removes_index_and_completes_remaining_parent() -> None:
    redis = FakeRedis(decode_responses=True)
    try:
        repository, children = await _repository_with_subtasks(
            redis,
            key_prefix='delete:rollup-done',
        )
        for child in children[:2]:
            doing = await repository.update_status_with_rollup(
                user_id='user-1',
                task_id=child.id,
                target_status=TaskStatus.DOING,
                expected_version=1,
                idempotency_key=f'doing:{child.id}',
            )
            await repository.update_status_with_rollup(
                user_id='user-1',
                task_id=child.id,
                target_status=TaskStatus.DONE,
                expected_version=doing.task.version,
                idempotency_key=f'done:{child.id}',
            )

        result = await repository.delete(
            user_id='user-1',
            task_id=children[2].id,
            expected_version=1,
            idempotency_key='delete-third',
        )
        remaining = await repository.list_children(
            user_id='user-1', parent_id='parent-1'
        )

        assert [task.id for task in remaining] == [
            children[0].id,
            children[1].id,
        ]
        assert result.parent_task is not None
        assert result.parent_task.status == TaskStatus.DONE
        assert result.parent_task.progress == 100
        assert result.parent_task.completed_at is not None
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_last_effective_child_reopens_parent() -> None:
    redis = FakeRedis(decode_responses=True)
    try:
        repository, children = await _repository_with_subtasks(
            redis,
            key_prefix='delete:rollup-empty',
        )
        for child in children[:2]:
            await repository.update_status_with_rollup(
                user_id='user-1',
                task_id=child.id,
                target_status=TaskStatus.CANCELLED,
                expected_version=1,
                idempotency_key=f'cancel:{child.id}',
            )
        doing = await repository.update_status_with_rollup(
            user_id='user-1',
            task_id=children[2].id,
            target_status=TaskStatus.DOING,
            expected_version=1,
            idempotency_key='doing:third',
        )
        done = await repository.update_status_with_rollup(
            user_id='user-1',
            task_id=children[2].id,
            target_status=TaskStatus.DONE,
            expected_version=doing.task.version,
            idempotency_key='done:third',
        )
        assert done.parent_task is not None
        assert done.parent_task.status == TaskStatus.DONE

        result = await repository.delete(
            user_id='user-1',
            task_id=children[2].id,
            expected_version=done.task.version,
            idempotency_key='delete-third',
        )
        assert result.parent_task is not None
        assert result.parent_task.status == TaskStatus.DOING
        assert result.parent_task.progress == 0
        assert result.parent_task.completed_at is None
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_delete_rejects_stale_version_cross_user_and_idempotency_conflict() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='delete:guards')
    try:
        await repository.create(_task(), idempotency_key='create')
        with pytest.raises(TaskVersionConflictError):
            await repository.delete(
                user_id='user-1',
                task_id='task-1',
                expected_version=2,
                idempotency_key='stale',
            )
        with pytest.raises(TaskNotFoundError):
            await repository.delete(
                user_id='user-2',
                task_id='task-1',
                expected_version=1,
                idempotency_key='cross-user',
            )
        await repository.delete(
            user_id='user-1',
            task_id='task-1',
            expected_version=1,
            idempotency_key='delete-1',
        )
        with pytest.raises(TaskRepositoryConsistencyError, match='different input'):
            await repository.delete(
                user_id='user-1',
                task_id='task-1',
                expected_version=2,
                idempotency_key='delete-1',
            )
    finally:
        await redis.aclose()
