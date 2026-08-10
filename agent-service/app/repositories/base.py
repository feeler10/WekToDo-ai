from abc import ABC, abstractmethod

from app.schemas.task import (
    Task,
    TaskListResponse,
    TaskQuery,
    TaskStatus,
    TaskUpdate,
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
        idempotency_key: str | None = None,
    ) -> Task:
        raise NotImplementedError
