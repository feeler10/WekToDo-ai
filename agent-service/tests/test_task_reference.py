import pytest

from app.matching.keyword import KeywordTaskMatcher
from app.schemas.task import Task, TaskStatus
from app.services.task_reference import parse_status_update


@pytest.mark.parametrize(
    ('message', 'reference', 'target'),
    [
        ('论文实验已经完成了', '论文实验', TaskStatus.DONE),
        ('把论文实验标记为进行中', '论文实验', TaskStatus.DOING),
        ('论文实验标记为阻塞', '论文实验', TaskStatus.BLOCKED),
        ('论文实验取消了', '论文实验', TaskStatus.CANCELLED),
    ],
)
def test_parse_natural_language_status_update(
    message: str,
    reference: str,
    target: TaskStatus,
) -> None:
    parsed = parse_status_update(message)
    assert parsed.reference == reference
    assert parsed.target_status == target


def test_resolve_reference_returns_all_exact_duplicate_titles() -> None:
    tasks = [
        Task(id='task-1', user_id='user-1', title='论文实验'),
        Task(id='task-2', user_id='user-1', title='论文实验'),
        Task(id='task-3', user_id='user-1', title='其他任务'),
    ]

    matches = KeywordTaskMatcher().match(
        reference='论文实验',
        user_id='user-1',
        tasks=tasks,
    ).tasks

    assert [task.id for task in matches] == ['task-1', 'task-2']
