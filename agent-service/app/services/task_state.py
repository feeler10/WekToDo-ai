from app.schemas.task import TaskStatus

_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.TODO: frozenset({TaskStatus.DOING, TaskStatus.CANCELLED}),
    TaskStatus.DOING: frozenset({TaskStatus.DONE, TaskStatus.BLOCKED}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.DOING}),
    TaskStatus.DONE: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

TERMINAL_TASK_STATUSES = frozenset(
    {TaskStatus.DONE, TaskStatus.CANCELLED}
)


class InvalidTaskStatusTransition(ValueError):
    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        super().__init__(f'Invalid task status transition: {current} -> {target}')
        self.current = current
        self.target = target


def is_status_transition_allowed(
    current: TaskStatus,
    target: TaskStatus,
    *,
    confirmed_reopen: bool = False,
    confirmed_restore: bool = False,
) -> bool:
    if current == target:
        return True
    if current == TaskStatus.DONE and target == TaskStatus.DOING:
        return confirmed_reopen
    if current == TaskStatus.CANCELLED and target == TaskStatus.TODO:
        return confirmed_restore
    return target in _ALLOWED_TRANSITIONS[current]


def validate_status_transition(
    current: TaskStatus,
    target: TaskStatus,
    *,
    confirmed_reopen: bool = False,
    confirmed_restore: bool = False,
) -> None:
    if not is_status_transition_allowed(
        current,
        target,
        confirmed_reopen=confirmed_reopen,
        confirmed_restore=confirmed_restore,
    ):
        raise InvalidTaskStatusTransition(current, target)
