import pytest

from app.tools.task_tools import create_task


class RecordingRepository:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, task: object, *, idempotency_key: str) -> object:
        self.calls += 1
        return task


@pytest.mark.anyio
async def test_create_task_refuses_unconfirmed_write() -> None:
    repository = RecordingRepository()

    with pytest.raises(PermissionError, match='requires user confirmation'):
        await create_task(
            repository=repository,
            task_input={'user_id': 'user-1', 'title': 'Unsafe task'},
            idempotency_key='request-1',
            confirmed=False,
        )

    assert repository.calls == 0
