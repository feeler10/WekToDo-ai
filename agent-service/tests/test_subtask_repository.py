from datetime import datetime, timezone

import pytest
from fakeredis.aioredis import FakeRedis

from app.repositories.exceptions import (
    TaskRepositoryConsistencyError,
    TaskVersionConflictError,
)
from app.repositories.redis_task import RedisTaskRepository
from app.schemas.subtask import SubtaskBatchCreate
from app.schemas.task import Task, TaskStatus


def _parent(*, status: TaskStatus = TaskStatus.DOING) -> Task:
    now = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return Task(
        id='parent-1',
        user_id='user-1',
        title='父任务',
        status=status,
        completed_at=now if status == TaskStatus.DONE else None,
        progress=100 if status == TaskStatus.DONE else 0,
        created_at=now,
        updated_at=now,
    )


def _batch(expected_parent_version: int = 1) -> SubtaskBatchCreate:
    return SubtaskBatchCreate.model_validate(
        {
            'user_id': 'user-1',
            'parent_task_id': 'parent-1',
            'expected_parent_version': expected_parent_version,
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


@pytest.mark.anyio
async def test_create_subtasks_batch_is_linked_ordered_and_idempotent() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='subtask:batch')
    try:
        await repository.create(_parent(), idempotency_key='parent')
        created = await repository.create_subtasks_batch(
            _batch(),
            idempotency_key='batch-1',
        )
        replay = await repository.create_subtasks_batch(
            _batch(),
            idempotency_key='batch-1',
        )
        children = await repository.list_children(
            user_id='user-1',
            parent_id='parent-1',
        )

        assert created.parent_task.version == 2
        assert [task.parent_id for task in children] == ['parent-1'] * 3
        assert [task.subtask_order for task in children] == [1, 2, 3]
        assert children[1].depends_on_task_ids == [children[0].id]
        assert replay.replayed is True
        assert [task.id for task in replay.subtasks] == [
            task.id for task in created.subtasks
        ]
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_batch_idempotency_key_rejects_different_payload() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='subtask:conflict')
    try:
        await repository.create(_parent(), idempotency_key='parent')
        await repository.create_subtasks_batch(
            _batch(),
            idempotency_key='batch-1',
        )
        changed = _batch().model_copy(deep=True)
        changed.items[0].title = '不同步骤'
        with pytest.raises(TaskRepositoryConsistencyError, match='different input'):
            await repository.create_subtasks_batch(
                changed,
                idempotency_key='batch-1',
            )
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_child_status_rolls_up_parent_and_reopens_it() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='subtask:rollup')
    try:
        await repository.create(_parent(), idempotency_key='parent')
        created = await repository.create_subtasks_batch(
            _batch(),
            idempotency_key='batch-1',
        )
        children = created.subtasks
        for child in children:
            doing = await repository.update_status_with_rollup(
                user_id='user-1',
                task_id=child.id,
                target_status=TaskStatus.DOING,
                expected_version=1,
                idempotency_key=f'doing-{child.id}',
            )
            done = await repository.update_status_with_rollup(
                user_id='user-1',
                task_id=child.id,
                target_status=TaskStatus.DONE,
                expected_version=doing.task.version,
                idempotency_key=f'done-{child.id}',
            )

        assert done.parent_task is not None
        assert done.parent_task.status == TaskStatus.DONE
        assert done.parent_task.progress == 100
        assert done.parent_task.completed_at is not None

        reopened = await repository.update_status_with_rollup(
            user_id='user-1',
            task_id=children[0].id,
            target_status=TaskStatus.DOING,
            expected_version=3,
            confirmed_reopen=True,
            idempotency_key='reopen-child',
        )
        assert reopened.parent_task is not None
        assert reopened.parent_task.status == TaskStatus.DOING
        assert reopened.parent_task.progress == 66
        assert reopened.parent_task.completed_at is None
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_all_cancelled_children_do_not_complete_parent() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='subtask:cancelled')
    try:
        await repository.create(_parent(), idempotency_key='parent')
        created = await repository.create_subtasks_batch(
            _batch(),
            idempotency_key='batch-1',
        )
        last = None
        for child in created.subtasks:
            last = await repository.update_status_with_rollup(
                user_id='user-1',
                task_id=child.id,
                target_status=TaskStatus.CANCELLED,
                expected_version=1,
                idempotency_key=f'cancel-{child.id}',
            )
        assert last is not None and last.parent_task is not None
        assert last.parent_task.status == TaskStatus.DOING
        assert last.parent_task.progress == 0
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_adding_subtasks_reopens_completed_parent() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='subtask:reopen-parent')
    try:
        await repository.create(
            _parent(status=TaskStatus.DONE),
            idempotency_key='parent',
        )
        result = await repository.create_subtasks_batch(
            _batch(),
            idempotency_key='batch-1',
        )

        assert result.parent_task.status == TaskStatus.DOING
        assert result.parent_task.progress == 0
        assert result.parent_task.completed_at is None
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_batch_rejects_stale_parent_version_without_writes() -> None:
    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='subtask:stale')
    try:
        await repository.create(_parent(), idempotency_key='parent')
        current = await repository.update_status(
            user_id='user-1',
            task_id='parent-1',
            target_status=TaskStatus.BLOCKED,
            expected_version=1,
        )
        assert current.version == 2
        with pytest.raises(TaskVersionConflictError):
            await repository.create_subtasks_batch(
                _batch(expected_parent_version=1),
                idempotency_key='batch-1',
            )
        assert await repository.list_children(
            user_id='user-1', parent_id='parent-1'
        ) == []
    finally:
        await redis.aclose()


@pytest.mark.anyio
async def test_concurrent_last_completions_converge_to_done_parent() -> None:
    import asyncio

    redis = FakeRedis(decode_responses=True)
    repository = RedisTaskRepository(redis, key_prefix='subtask:concurrent-done')
    try:
        await repository.create(_parent(), idempotency_key='parent')
        created = await repository.create_subtasks_batch(
            _batch(),
            idempotency_key='batch-1',
        )
        doing_children = []
        for child in created.subtasks:
            result = await repository.update_status_with_rollup(
                user_id='user-1',
                task_id=child.id,
                target_status=TaskStatus.DOING,
                expected_version=1,
                idempotency_key=f'doing-{child.id}',
            )
            doing_children.append(result.task)
        first_done = await repository.update_status_with_rollup(
            user_id='user-1',
            task_id=doing_children[0].id,
            target_status=TaskStatus.DONE,
            expected_version=2,
            idempotency_key='done-first',
        )
        assert first_done.parent_task is not None
        results = await asyncio.gather(
            *(
                repository.update_status_with_rollup(
                    user_id='user-1',
                    task_id=child.id,
                    target_status=TaskStatus.DONE,
                    expected_version=2,
                    idempotency_key=f'done-{child.id}',
                )
                for child in doing_children[1:]
            )
        )
        parent = await repository.get(
            user_id='user-1', task_id='parent-1'
        )
        assert parent is not None
        assert parent.status == TaskStatus.DONE
        assert parent.progress == 100
        assert any(
            result.parent_task is not None
            and result.parent_task.status == TaskStatus.DONE
            for result in results
        )
    finally:
        await redis.aclose()
