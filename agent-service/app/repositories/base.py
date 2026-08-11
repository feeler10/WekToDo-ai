from abc import ABC, abstractmethod

from app.schemas.task import (
    Task,
    TaskListResponse,
    TaskQuery,
    TaskStatus,
    TaskUpdate,
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


class TaskRepository(ABC):
    @abstractmethod
    async def create(self, task: Task, *, idempotency_key: str) -> Task:
        raise NotImplementedError

    @abstractmethod
    async def get(self, *, user_id: str, task_id: str) -> Task | None:
        raise NotImplementedError

    @abstractmethod
    async def list_tasks(self, query: TaskQuery) -> TaskListResponse:
        raise NotImplementedError

    @abstractmethod
    async def update(
        self,
        *,
        user_id: str,
        task_id: str,
        update: TaskUpdate,
        idempotency_key: str | None = None,
    ) -> Task:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    async def list_children(
        self,
        *,
        user_id: str,
        parent_id: str,
    ) -> list[Task]:
        result = await self.list_tasks(TaskQuery(user_id=user_id, limit=100))
        return [task for task in result.items if task.parent_id == parent_id]

    async def create_subtasks_batch(
        self,
        batch: SubtaskBatchCreate,
        *,
        idempotency_key: str,
    ) -> SubtaskBatchResult:
        raise NotImplementedError

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
        task = await self.update_status(
            user_id=user_id,
            task_id=task_id,
            target_status=target_status,
            expected_version=expected_version,
            confirmed_reopen=confirmed_reopen,
            confirmed_restore=confirmed_restore,
            idempotency_key=idempotency_key,
        )
        return TaskStatusUpdateResult(task=task)

    async def delete(
        self,
        *,
        user_id: str,
        task_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> TaskDeleteResult:
        raise NotImplementedError

    async def delete_batch(
        self,
        batch: TaskDeleteBatch,
        *,
        idempotency_key: str,
    ) -> TaskDeleteBatchResult:
        raise NotImplementedError
