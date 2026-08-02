import pytest

from app.schemas.task import TaskStatus
from app.services.task_state import (
    InvalidTaskStatusTransition,
    is_status_transition_allowed,
    validate_status_transition,
)

NORMAL_TRANSITIONS = [
    (TaskStatus.TODO, TaskStatus.DOING),
    (TaskStatus.TODO, TaskStatus.CANCELLED),
    (TaskStatus.DOING, TaskStatus.DONE),
    (TaskStatus.DOING, TaskStatus.BLOCKED),
    (TaskStatus.BLOCKED, TaskStatus.DOING),
]


def test_complete_status_transition_matrix() -> None:
    for current in TaskStatus:
        for target in TaskStatus:
            expected = current == target or (current, target) in NORMAL_TRANSITIONS
            assert is_status_transition_allowed(current, target) is expected


def test_done_can_reopen_only_with_confirmation() -> None:
    assert not is_status_transition_allowed(TaskStatus.DONE, TaskStatus.DOING)
    assert is_status_transition_allowed(
        TaskStatus.DONE,
        TaskStatus.DOING,
        confirmed_reopen=True,
    )


@pytest.mark.parametrize(('current', 'target'), NORMAL_TRANSITIONS)
def test_validator_accepts_documented_transitions(
    current: TaskStatus,
    target: TaskStatus,
) -> None:
    validate_status_transition(current, target)


def test_validator_rejects_illegal_transition() -> None:
    with pytest.raises(InvalidTaskStatusTransition) as error:
        validate_status_transition(TaskStatus.TODO, TaskStatus.DONE)

    assert error.value.current == TaskStatus.TODO
    assert error.value.target == TaskStatus.DONE
