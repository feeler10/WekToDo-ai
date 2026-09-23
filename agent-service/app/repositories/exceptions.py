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


class IdempotencyConflictError(TaskRepositoryConsistencyError):
    pass


class TaskDeletionBlockedError(TaskRepositoryError):
    pass


class ConversationRepositoryError(RuntimeError):
    pass


class ConversationRepositoryConcurrencyError(ConversationRepositoryError):
    pass


class ConversationRepositoryConsistencyError(ConversationRepositoryError):
    pass


class ObservabilityRepositoryError(RuntimeError):
    pass


class ObservabilityRepositoryConsistencyError(ObservabilityRepositoryError):
    pass


class ToolAuditPersistenceError(ObservabilityRepositoryError):
    pass
