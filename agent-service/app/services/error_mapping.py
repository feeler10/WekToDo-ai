from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from redis.exceptions import RedisError

from app.repositories.exceptions import (
    IdempotencyConflictError,
    ConversationRepositoryConcurrencyError,
    ConversationRepositoryConsistencyError,
    TaskAlreadyExistsError,
    TaskDeletionBlockedError,
    TaskNotFoundError,
    TaskRepositoryConcurrencyError,
    TaskRepositoryConsistencyError,
    TaskVersionConflictError,
    ToolAuditPersistenceError,
)
from app.schemas.errors import AgentErrorInfo
from app.services.task_state import InvalidTaskStatusTransition
from app.services.exceptions import (
    ComponentNotConfiguredError,
    ModelOutputInvalidError,
    ModelUnavailableError,
)


@dataclass(frozen=True)
class ErrorDescriptor:
    code: str
    message: str
    retryable: bool = False


_ERRORS: tuple[tuple[type[BaseException], ErrorDescriptor], ...] = (
    (
        ComponentNotConfiguredError,
        ErrorDescriptor(
            'service_unavailable',
            '任务助手组件暂时不可用，请稍后重试。',
            True,
        ),
    ),
    (
        ModelOutputInvalidError,
        ErrorDescriptor(
            'model_output_invalid',
            'AI 返回结果不完整，请重新描述后再试。',
            True,
        ),
    ),
    (
        ModelUnavailableError,
        ErrorDescriptor(
            'model_unavailable',
            'AI 服务暂时不可用，请稍后重试。',
            True,
        ),
    ),
    (
        ToolAuditPersistenceError,
        ErrorDescriptor(
            'audit_unavailable',
            '操作审计暂时不可用，为保护数据，本次操作未执行。',
            True,
        ),
    ),
    (
        IdempotencyConflictError,
        ErrorDescriptor(
            'idempotency_conflict',
            '相同请求标识对应了不同操作，本次请求未执行。',
        ),
    ),
    (
        TaskNotFoundError,
        ErrorDescriptor('task_not_found', '任务不存在或不属于当前用户。'),
    ),
    (
        TaskVersionConflictError,
        ErrorDescriptor(
            'task_version_conflict',
            '任务已被修改，请重新查看后再操作。',
            True,
        ),
    ),
    (
        InvalidTaskStatusTransition,
        ErrorDescriptor(
            'invalid_status_transition',
            '当前任务状态不支持此操作。',
        ),
    ),
    (
        TaskDeletionBlockedError,
        ErrorDescriptor(
            'task_deletion_blocked',
            '任务存在子任务或依赖关系，暂时无法删除。',
        ),
    ),
    (
        TaskAlreadyExistsError,
        ErrorDescriptor('task_already_exists', '任务已经存在。'),
    ),
    (
        (TaskRepositoryConcurrencyError),
        ErrorDescriptor(
            'repository_busy',
            '任务正在被其他请求修改，请稍后重试。',
            True,
        ),
    ),
    (
        ConversationRepositoryConcurrencyError,
        ErrorDescriptor(
            'repository_busy',
            '数据正在被其他请求修改，请稍后重试。',
            True,
        ),
    ),
    (
        TaskRepositoryConsistencyError,
        ErrorDescriptor(
            'repository_consistency_error',
            '任务数据状态不一致，请重新查看后再操作。',
            True,
        ),
    ),
    (
        ConversationRepositoryConsistencyError,
        ErrorDescriptor(
            'repository_consistency_error',
            '会话数据状态不一致，请稍后重试。',
            True,
        ),
    ),
    (
        RedisError,
        ErrorDescriptor(
            'redis_unavailable',
            '任务存储暂时不可用，请稍后重试。',
            True,
        ),
    ),
    (
        PermissionError,
        ErrorDescriptor(
            'confirmation_required',
            '此操作需要经过用户确认。',
        ),
    ),
    (
        ValidationError,
        ErrorDescriptor(
            'invalid_operation_data',
            '操作数据不完整或格式不正确，请重新发起。',
        ),
    ),
)

_INTERNAL = ErrorDescriptor(
    'internal_error',
    '系统处理失败，请稍后重试并提供追踪编号。',
    True,
)


def map_exception(
    exc: BaseException,
    *,
    trace_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AgentErrorInfo:
    descriptor = next(
        (
            candidate
            for exception_type, candidate in _ERRORS
            if isinstance(exc, exception_type)
        ),
        _INTERNAL,
    )
    return AgentErrorInfo(
        code=descriptor.code,
        message=descriptor.message,
        retryable=descriptor.retryable,
        details=details,
        trace_id=trace_id,
    )


def map_legacy_graph_error(
    message: str | None,
    *,
    trace_id: str | None = None,
) -> AgentErrorInfo:
    return AgentErrorInfo(
        code='workflow_error',
        message=_INTERNAL.message,
        retryable=True,
        trace_id=trace_id,
    )


def error_state(
    exc: BaseException,
    *,
    trace_id: str | None = None,
) -> dict[str, object]:
    error = map_exception(exc, trace_id=trace_id)
    return {
        'error': error.model_dump(mode='json'),
        'error_message': error.message,
        'final_response': error.message,
    }
