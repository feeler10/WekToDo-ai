class TaskRepositoryError(RuntimeError):
    pass


class TaskNotFoundError(TaskRepositoryError):
    pass


class TaskAlreadyExistsError(TaskRepositoryError):
    pass


class TaskVersionConflictError(TaskRepositoryError):
    pass


class TaskRepositoryConcurrencyError(TaskRepositoryError):
    pass


class TaskRepositoryConsistencyError(TaskRepositoryError):
    pass


class TaskDeletionBlockedError(TaskRepositoryError):
    pass
